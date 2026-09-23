from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .models import Permission, ProjectContext, ToolSpec
from .workspace import WorkspaceManager

if TYPE_CHECKING:
    from .executor import ContainerExecutor

ToolHandler = Callable[[ProjectContext, dict[str, Any]], Any]
MAX_TEXT_BYTES = 1_000_000


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {name}") from error

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(item.spec for item in self._tools.values())


def _list_files(context: ProjectContext, arguments: dict[str, Any]) -> list[str]:
    base = WorkspaceManager.safe_content_path(context, str(arguments.get("path", "inputs")))
    if not base.exists():
        return []
    if not base.is_dir():
        raise ValueError("list_files expects a directory.")
    files: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(context.root))
        WorkspaceManager.safe_content_path(context, relative)
        files.append(relative.replace("\\", "/"))
    return sorted(files)


def _read_text(context: ProjectContext, arguments: dict[str, Any]) -> str:
    path = WorkspaceManager.safe_content_path(context, str(arguments["path"]))
    if path.suffix.lower() not in {".md", ".txt", ".json", ".csv"}:
        raise ValueError("Only text, Markdown, JSON and CSV files are readable.")
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError(f"File exceeds the {MAX_TEXT_BYTES}-byte read limit.")
    return path.read_text(encoding="utf-8")


def _write_text(context: ProjectContext, arguments: dict[str, Any]) -> str:
    path = WorkspaceManager.safe_content_path(context, str(arguments["path"]))
    relative = path.relative_to(context.root.resolve())
    if relative.parts[0] not in {"outputs", "work"}:
        raise ValueError("Agent writes are limited to outputs and work.")
    content = str(arguments["content"])
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"Content exceeds the {MAX_TEXT_BYTES}-byte write limit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(context.root)).replace("\\", "/")


def build_default_registry(
    container_executor: ContainerExecutor | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "list_files",
            "List files beneath an allowed project content directory. The path must "
            "be inputs, outputs, work, or a descendant; project root, '.', '/', and "
            "empty paths are forbidden.",
            Permission.READ,
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        _list_files,
    )
    registry.register(
        ToolSpec(
            "read_text",
            "Read an approved text file whose path starts with inputs/, outputs/, "
            "or work/.",
            Permission.READ,
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        _read_text,
    )
    registry.register(
        ToolSpec(
            "write_text",
            "Write a UTF-8 text artifact whose path starts with outputs/ or work/.",
            Permission.WRITE,
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        _write_text,
    )
    if container_executor is not None:
        registry.register(
            ToolSpec(
                "container_exec",
                "Run an allowlisted executable in the isolated project container. "
                "Arguments must be an argv array; shell command strings are forbidden.",
                Permission.EXECUTE,
                {
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        }
                    },
                    "required": ["argv"],
                    "additionalProperties": False,
                },
            ),
            lambda context, arguments: container_executor.execute(
                context, arguments.get("argv")
            ).as_dict(),
        )
    return registry
