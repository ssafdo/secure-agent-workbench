from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Permission(StrEnum):
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    EXECUTE = "execute"


class ToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    session_id: str
    root: Path
    allowed_permissions: frozenset[Permission] = field(
        default_factory=lambda: frozenset({Permission.READ, Permission.WRITE})
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: Permission
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    output: Any = None
    error: str | None = None
    error_type: str | None = None


class WorkbenchError(RuntimeError):
    """Base error for expected workbench failures."""


class PathViolation(WorkbenchError):
    """Raised when a requested path escapes its project workspace."""


class PermissionDenied(WorkbenchError):
    """Raised when policy rejects a tool call."""


class StepBudgetExceeded(WorkbenchError):
    """Raised when an agent exceeds its configured tool-call budget."""
