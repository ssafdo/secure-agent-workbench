from __future__ import annotations

from time import perf_counter
from typing import Any

from .models import (
    Permission,
    PermissionDenied,
    ProjectContext,
    StepBudgetExceeded,
    ToolResult,
    ToolStatus,
)
from .tools import ToolRegistry
from .tracing import TraceStore
from .workspace import WorkspaceManager


class AgentRuntime:
    """Policy enforcement point for every agent tool call."""

    def __init__(
        self,
        context: ProjectContext,
        workspace: WorkspaceManager,
        registry: ToolRegistry,
        traces: TraceStore | None = None,
        max_steps: int = 12,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive.")
        self.context = context
        self.workspace = workspace
        self.registry = registry
        self.traces = traces or TraceStore()
        self.max_steps = max_steps
        self.steps = 0
        self.tool_events: list[dict[str, Any]] = []
        self.model_events: list[dict[str, Any]] = []
        self.context_events: list[dict[str, Any]] = []
        self.reflection_events: list[dict[str, Any]] = []
        self.routing_events: list[dict[str, Any]] = []

    def record_agent_route(
        self,
        supervisor: str,
        specialist: str,
        reason: str,
        signal_count: int,
    ) -> None:
        event = {
            "event": "agent_route",
            "supervisor": supervisor,
            "specialist": specialist,
            "reason": reason,
            "signalCount": signal_count,
        }
        self.routing_events.append(event)
        self.traces.append(self.context, event)

    def record_model_call(
        self,
        provider: str,
        turn: int,
        status: str,
        usage: dict[str, int | float] | None = None,
        error_type: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "event": "model_call",
            "provider": provider,
            "turn": turn,
            "status": status,
            "usage": usage,
            "error_type": error_type,
        }
        self.model_events.append(event)
        self.traces.append(self.context, event)

    def record_context_compaction(self, metadata: dict[str, int | bool]) -> None:
        event: dict[str, Any] = {"event": "context_compaction", **metadata}
        self.context_events.append(event)
        self.traces.append(self.context, event)

    def record_reflection(self, turn: int, trigger: str, error_type: str) -> None:
        event = {
            "event": "reflection",
            "turn": turn,
            "trigger": trigger,
            "error_type": error_type,
        }
        self.reflection_events.append(event)
        self.traces.append(self.context, event)

    def call(self, tool_name: str, arguments: dict[str, Any], approved: bool = False) -> ToolResult:
        started = perf_counter()
        status = ToolStatus.FAILED
        error_message: str | None = None
        error_type: str | None = None
        output: Any = None
        try:
            if self.steps >= self.max_steps:
                raise StepBudgetExceeded(f"Tool-call budget of {self.max_steps} exceeded.")
            self.steps += 1
            tool = self.registry.get(tool_name)
            permission = tool.spec.permission
            if permission not in self.context.allowed_permissions:
                raise PermissionDenied(f"Permission is disabled: {permission.value}")
            if permission in {Permission.WRITE, Permission.EXECUTE} and not approved:
                raise PermissionDenied(
                    f"{permission.value.capitalize()} operation requires explicit approval."
                )
            with self.workspace.project_lock(self.context.project_id):
                output = tool.handler(self.context, arguments)
            status = ToolStatus.SUCCEEDED
            return ToolResult(status=status, output=output)
        except PermissionDenied as error:
            status = ToolStatus.DENIED
            error_message = str(error)
            error_type = type(error).__name__
            return ToolResult(
                status=status, error=error_message, error_type=error_type
            )
        except Exception as error:  # Convert expected tool failures into observable results.
            error_message = f"{type(error).__name__}: {error}"
            error_type = type(error).__name__
            return ToolResult(
                status=status, error=error_message, error_type=error_type
            )
        finally:
            duration_ms = round((perf_counter() - started) * 1000, 3)
            if output is None:
                output_metadata = None
            elif hasattr(output, "__len__"):
                output_metadata = {"type": type(output).__name__, "size": len(output)}
            else:
                output_metadata = {"type": type(output).__name__}
            event = {
                "event": "tool_call",
                "tool": tool_name,
                "argument_keys": sorted(arguments.keys()),
                "approved": approved,
                "status": status.value,
                "error": error_message,
                "error_type": error_type,
                "output_metadata": output_metadata,
                "duration_ms": duration_ms,
                "step": self.steps,
            }
            self.tool_events.append(event)
            self.traces.append(self.context, event)
