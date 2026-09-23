from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"topic": {"type": "string", "minLength": 1, "maxLength": 80}},
    "required": ["topic"],
    "additionalProperties": False,
}
ANNOTATIONS = types.ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


async def list_tools(
    _context: object, _params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="project_summary",
                description="Read a fixed summary of the secure workbench boundary.",
                inputSchema=SCHEMA,
                annotations=ANNOTATIONS,
            )
        ]
    )


async def call_tool(
    _context: object, params: types.CallToolRequestParams
) -> types.CallToolResult:
    if params.name != "project_summary":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="unknown tool")],
            isError=True,
        )
    topic = (params.arguments or {}).get("topic")
    if not isinstance(topic, str) or not topic:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="invalid arguments")],
            isError=True,
        )
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=(
                    "MCP tools are admitted through a read-only allowlist, strict schema, "
                    "bounded output, timeout, AgentRuntime permissions, and redacted trace."
                ),
            )
        ]
    )


server = Server(
    "secure-agent-workbench-smoke",
    version="1.0.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import anyio

    anyio.run(main)
