from __future__ import annotations

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence, TypeVar

from .models import Permission, ProjectContext, ToolSpec, WorkbenchError
from .tools import ToolRegistry

MCP_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MCP_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
MAX_DESCRIPTION_CHARS = 1_000
DEFAULT_OUTPUT_BYTES = 64 * 1024
_FORBIDDEN_DESCRIPTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|password|credential|secret|token)", re.IGNORECASE),
    re.compile(r"(?:run|execute|invoke)\s+(?:a\s+)?(?:shell|command|script)", re.IGNORECASE),
)
_FORBIDDEN_SCHEMA_KEYS = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "$recursiveRef",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
        "unevaluatedProperties",
        "contentEncoding",
        "contentMediaType",
    }
)
_ALLOWED_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)
_T = TypeVar("_T")


class MCPPolicyError(WorkbenchError):
    """Raised when a server or discovered tool violates the local MCP policy."""


class MCPTimeoutError(WorkbenchError):
    """Raised when an MCP lifecycle operation exceeds its hard deadline."""


class MCPToolCallError(WorkbenchError):
    """Raised when an admitted MCP tool fails or returns unsupported output."""


@dataclass(frozen=True)
class MCPToolPolicy:
    source_name: str
    permission: Permission = Permission.READ
    description: str | None = None

    def __post_init__(self) -> None:
        if not MCP_NAME_PATTERN.fullmatch(self.source_name):
            raise MCPPolicyError(f"Unsafe MCP tool name: {self.source_name!r}")
        if self.permission is not Permission.READ:
            raise MCPPolicyError("Initial MCP support only admits read-only tools.")
        if self.description is not None and (
            not self.description.strip() or len(self.description) > MAX_DESCRIPTION_CHARS
        ):
            raise MCPPolicyError("Local MCP tool description is empty or too long.")


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    command: str
    args: tuple[str, ...] = ()
    tools: tuple[MCPToolPolicy, ...] = ()
    timeout_seconds: float = 5.0
    startup_timeout_seconds: float = 5.0
    max_output_bytes: int = DEFAULT_OUTPUT_BYTES
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not MCP_NAME_PATTERN.fullmatch(self.server_id):
            raise MCPPolicyError(f"Unsafe MCP server id: {self.server_id!r}")
        command = Path(self.command)
        if not command.is_absolute() or not command.is_file():
            raise MCPPolicyError("MCP command must be an existing absolute file path.")
        if not self.tools:
            raise MCPPolicyError("MCP server requires an explicit non-empty tool allowlist.")
        names = [tool.source_name for tool in self.tools]
        if len(names) != len(set(names)):
            raise MCPPolicyError("MCP tool allowlist contains duplicate names.")
        if not 0 < self.timeout_seconds <= 60:
            raise MCPPolicyError("MCP timeout must be greater than 0 and at most 60 seconds.")
        if not 0 < self.startup_timeout_seconds <= 60:
            raise MCPPolicyError(
                "MCP startup timeout must be greater than 0 and at most 60 seconds."
            )
        if not 1 <= self.max_output_bytes <= 1_000_000:
            raise MCPPolicyError("MCP output limit must be between 1 and 1000000 bytes.")
        if self.cwd is not None and not Path(self.cwd).is_absolute():
            raise MCPPolicyError("MCP working directory must be absolute.")
        for name, value in self.env.items():
            if not MCP_ENV_NAME_PATTERN.fullmatch(name):
                raise MCPPolicyError(f"Unsafe MCP environment name: {name!r}")
            if re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH", name):
                raise MCPPolicyError("MCP environment cannot contain credential-like names.")
            if not isinstance(value, str):
                raise MCPPolicyError("MCP environment values must be strings.")
        if any("\x00" in item for item in (self.command, *self.args)):
            raise MCPPolicyError("MCP command and arguments cannot contain null bytes.")


@dataclass(frozen=True)
class DiscoveredMCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only_hint: bool | None
    destructive_hint: bool | None
    open_world_hint: bool | None


@dataclass(frozen=True)
class AdmittedMCPTool:
    source_name: str
    registered_name: str
    description: str
    input_schema: dict[str, Any]
    fingerprint: str


def _schema_error(message: str) -> MCPPolicyError:
    return MCPPolicyError(f"MCP input schema rejected: {message}")


def _inspect_schema_node(node: Any, path: str = "$") -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _inspect_schema_node(item, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    forbidden = _FORBIDDEN_SCHEMA_KEYS.intersection(node)
    if forbidden:
        raise _schema_error(f"unsupported keyword {sorted(forbidden)[0]!r} at {path}.")
    schema_type = node.get("type")
    if isinstance(schema_type, list) or (
        schema_type is not None and schema_type not in _ALLOWED_SCHEMA_TYPES
    ):
        raise _schema_error(f"unsupported type at {path}.")
    if schema_type == "object":
        properties = node.get("properties")
        if not isinstance(properties, dict):
            raise _schema_error(f"object properties must be an object at {path}.")
        if node.get("additionalProperties") is not False:
            raise _schema_error(f"additionalProperties must be false at {path}.")
        required = node.get("required")
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise _schema_error(f"required must be a string array at {path}.")
        if len(required) != len(set(required)) or set(required) != set(properties):
            raise _schema_error(f"every property must be required exactly once at {path}.")
    if schema_type == "array" and "items" not in node:
        raise _schema_error(f"array items are required at {path}.")
    for key, value in node.items():
        _inspect_schema_node(value, f"{path}.{key}")


def validate_mcp_schema(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise _schema_error("root must be an object.")
    _inspect_schema_node(schema)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise MCPPolicyError("Install the 'mcp' optional dependency.") from error
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise _schema_error(f"invalid JSON Schema ({type(error).__name__}).") from error


def validate_mcp_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise MCPPolicyError("MCP arguments must be an object.")
    from jsonschema import Draft202012Validator

    errors = sorted(Draft202012Validator(schema).iter_errors(arguments), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise MCPPolicyError(
            f"MCP arguments failed schema validation at {location} ({error.validator})."
        )


def _tool_fingerprint(tool: DiscoveredMCPTool) -> str:
    return json.dumps(
        {
            "description": tool.description,
            "inputSchema": tool.input_schema,
            "readOnlyHint": tool.read_only_hint,
            "destructiveHint": tool.destructive_hint,
            "openWorldHint": tool.open_world_hint,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def admit_mcp_tools(
    config: MCPServerConfig, discovered: Sequence[DiscoveredMCPTool]
) -> tuple[AdmittedMCPTool, ...]:
    discovered_names = [tool.name for tool in discovered]
    if len(discovered_names) != len(set(discovered_names)):
        raise MCPPolicyError("MCP server advertised duplicate tool names.")
    by_name = {tool.name: tool for tool in discovered}
    admitted: list[AdmittedMCPTool] = []
    for policy in config.tools:
        tool = by_name.get(policy.source_name)
        if tool is None:
            raise MCPPolicyError(f"Allowlisted MCP tool was not advertised: {policy.source_name}")
        if not isinstance(tool.description, str) or not tool.description.strip():
            raise MCPPolicyError(f"MCP tool {tool.name!r} requires a description.")
        if len(tool.description) > MAX_DESCRIPTION_CHARS:
            raise MCPPolicyError(f"MCP tool {tool.name!r} description is too long.")
        if any(pattern.search(tool.description) for pattern in _FORBIDDEN_DESCRIPTION_PATTERNS):
            raise MCPPolicyError(f"MCP tool {tool.name!r} has a dangerous description.")
        if tool.read_only_hint is not True:
            raise MCPPolicyError(f"MCP tool {tool.name!r} must declare readOnlyHint=true.")
        if tool.destructive_hint is not False:
            raise MCPPolicyError(f"MCP tool {tool.name!r} must declare destructiveHint=false.")
        if tool.open_world_hint is not False:
            raise MCPPolicyError(f"MCP tool {tool.name!r} must declare openWorldHint=false.")
        validate_mcp_schema(tool.input_schema)
        registered_name = f"mcp_{config.server_id}_{tool.name}"
        admitted.append(
            AdmittedMCPTool(
                source_name=tool.name,
                registered_name=registered_name,
                description=(
                    policy.description
                    or f"Read data from the approved MCP tool '{tool.name}'."
                ),
                input_schema=tool.input_schema,
                fingerprint=_tool_fingerprint(tool),
            )
        )
    return tuple(admitted)


def _run_async(factory: Callable[[], Awaitable[_T]]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-bridge") as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


def _find_group_error(group: BaseExceptionGroup) -> BaseException | None:
    for error in group.exceptions:
        if isinstance(error, (WorkbenchError, TimeoutError)):
            return error
        if isinstance(error, BaseExceptionGroup):
            nested = _find_group_error(error)
            if nested is not None:
                return nested
    return None


def _as_discovered(tool: Any) -> DiscoveredMCPTool:
    annotations = tool.annotations
    return DiscoveredMCPTool(
        name=tool.name,
        description=tool.description or "",
        input_schema=tool.input_schema,
        read_only_hint=None if annotations is None else annotations.read_only_hint,
        destructive_hint=None if annotations is None else annotations.destructive_hint,
        open_world_hint=None if annotations is None else annotations.open_world_hint,
    )


async def _with_session(
    config: MCPServerConfig, operation: Callable[[Any], Awaitable[_T]]
) -> _T:
    try:
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise MCPPolicyError("Install with 'pip install -e .[mcp]' to enable MCP.") from error

    parameters = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env),
        cwd=config.cwd,
    )
    try:
        with anyio.fail_after(config.startup_timeout_seconds + config.timeout_seconds):
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(parameters, errlog=errlog) as (read, write):
                    async with ClientSession(
                        read,
                        write,
                        read_timeout_seconds=config.startup_timeout_seconds,
                    ) as session:
                        await session.initialize()
                        return await operation(session)
    except BaseExceptionGroup as error:
        policy_error = _find_group_error(error)
        if isinstance(policy_error, TimeoutError):
            raise MCPTimeoutError(
                f"MCP operation exceeded {config.timeout_seconds:g} seconds."
            ) from error
        if policy_error is not None:
            raise policy_error from error
        raise
    except TimeoutError as error:
        raise MCPTimeoutError(
            f"MCP operation exceeded {config.timeout_seconds:g} seconds."
        ) from error


async def _discover(config: MCPServerConfig) -> tuple[DiscoveredMCPTool, ...]:
    async def operation(session: Any) -> tuple[DiscoveredMCPTool, ...]:
        result = await session.list_tools()
        return tuple(_as_discovered(tool) for tool in result.tools)

    return await _with_session(config, operation)


def discover_mcp_tools(config: MCPServerConfig) -> tuple[AdmittedMCPTool, ...]:
    return admit_mcp_tools(config, _run_async(lambda: _discover(config)))


def _normalize_output(result: Any, max_output_bytes: int) -> Any:
    if result.is_error:
        raise MCPToolCallError("MCP server reported a tool error.")
    text_parts: list[str] = []
    for item in result.content:
        if getattr(item, "type", None) != "text" or not isinstance(
            getattr(item, "text", None), str
        ):
            raise MCPToolCallError("MCP tool returned an unsupported content type.")
        text_parts.append(item.text)
    structured = result.structured_content
    if structured is None:
        output: Any = "\n".join(text_parts)
    elif text_parts:
        output = {"text": text_parts, "structured": structured}
    else:
        output = structured
    try:
        encoded = json.dumps(
            output, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MCPToolCallError("MCP tool returned non-JSON output.") from error
    if len(encoded) > max_output_bytes:
        raise MCPToolCallError(
            f"MCP tool output exceeds the {max_output_bytes}-byte limit."
        )
    return output


async def _call_admitted_tool(
    config: MCPServerConfig,
    admitted: AdmittedMCPTool,
    arguments: dict[str, Any],
) -> Any:
    async def operation(session: Any) -> Any:
        listed = await session.list_tools()
        discovered = tuple(_as_discovered(tool) for tool in listed.tools)
        current = admit_mcp_tools(config, discovered)
        match = next(
            (tool for tool in current if tool.source_name == admitted.source_name), None
        )
        if match is None or match.fingerprint != admitted.fingerprint:
            raise MCPPolicyError("MCP tool definition changed after admission.")
        async with asyncio.timeout(config.timeout_seconds):
            result = await session.call_tool(
                admitted.source_name,
                arguments,
                read_timeout_seconds=config.startup_timeout_seconds,
            )
        return _normalize_output(result, config.max_output_bytes)

    return await _with_session(config, operation)


def register_mcp_server(
    registry: ToolRegistry, config: MCPServerConfig
) -> tuple[ToolSpec, ...]:
    admitted_tools = discover_mcp_tools(config)
    specs: list[ToolSpec] = []
    for admitted in admitted_tools:
        spec = ToolSpec(
            admitted.registered_name,
            admitted.description,
            Permission.READ,
            admitted.input_schema,
        )

        def handler(
            _context: ProjectContext,
            arguments: dict[str, Any],
            tool: AdmittedMCPTool = admitted,
        ) -> Any:
            validate_mcp_arguments(tool.input_schema, arguments)
            return _run_async(lambda: _call_admitted_tool(config, tool, arguments))

        registry.register(spec, handler)
        specs.append(spec)
    return tuple(specs)
