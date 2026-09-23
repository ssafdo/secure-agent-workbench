from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("workbench-mcp-fixture", version="1.0.0")
if pid_path := os.getenv("MCP_FIXTURE_PID_PATH"):
    Path(pid_path).write_text(str(os.getpid()), encoding="ascii")
SAFE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@server.tool(annotations=SAFE_ANNOTATIONS, structured_output=False)
def echo_note(note: str) -> str:
    """Return the supplied note as bounded text."""
    return note


@server.tool(annotations=SAFE_ANNOTATIONS, structured_output=False)
def environment_probe() -> str:
    """Report whether the fixture-only environment marker is present."""
    return "present" if os.getenv("MCP_FIXTURE_HOST_SECRET") else "absent"


@server.tool(annotations=SAFE_ANNOTATIONS, structured_output=False)
async def slow_read(delay_seconds: float) -> str:
    """Wait for a bounded interval before returning a read result."""
    await asyncio.sleep(delay_seconds)
    return "finished"


@server.tool(annotations=SAFE_ANNOTATIONS, structured_output=False)
def large_read(size: int) -> str:
    """Return a deterministic text payload of the requested size."""
    return "x" * size


# MCPServer's generated Pydantic schemas are intentionally permissive by default.
# This fixture advertises the explicit strict shape required by the workbench gate.
for fixture_tool in server._tool_manager._tools.values():
    fixture_tool.parameters["additionalProperties"] = False
    fixture_tool.parameters.setdefault(
        "required", list(fixture_tool.parameters.get("properties", {}))
    )


if __name__ == "__main__":
    server.run("stdio")
