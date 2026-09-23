from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .models import PathViolation, ProjectContext


class WorkspaceManager:
    """Creates project workspaces and enforces their path boundary."""

    def __init__(self, runtime_root: Path, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("Workspace secret must contain at least 16 bytes.")
        self.runtime_root = runtime_root.resolve()
        projects_path = self.runtime_root / "projects"
        projects_path.mkdir(parents=True, exist_ok=True)
        self.projects_root = projects_path.resolve()
        try:
            self.projects_root.relative_to(self.runtime_root)
        except ValueError as error:
            raise PathViolation("Projects directory escapes the runtime root.") from error
        self._secret = secret
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def project_id(self, feature_id: str, user_id: str, conversation_id: str) -> str:
        values = (feature_id, user_id, conversation_id)
        if any(not value.strip() for value in values):
            raise ValueError("feature_id, user_id and conversation_id are required.")
        payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:32]

    def create_project(
        self,
        feature_id: str,
        user_id: str,
        conversation_id: str,
        session_id: str,
    ) -> ProjectContext:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
            raise ValueError("session_id contains unsupported characters.")
        project_id = self.project_id(feature_id, user_id, conversation_id)
        root = (self.projects_root / project_id).resolve()
        try:
            root.relative_to(self.projects_root)
        except ValueError as error:
            raise PathViolation("Project directory escapes the projects root.") from error
        for name in ("inputs", "outputs", "work", ".agent/traces", ".agent/sessions"):
            (root / name).mkdir(parents=True, exist_ok=True)
        metadata_path = root / ".agent" / "metadata.json"
        if not metadata_path.exists():
            metadata = {
                "project_id": project_id,
                "feature_id": feature_id,
                "created_at": datetime.now(UTC).isoformat(),
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return ProjectContext(project_id=project_id, session_id=session_id, root=root)

    @staticmethod
    def safe_path(context: ProjectContext, relative_path: str) -> Path:
        requested = Path(relative_path)
        if requested.is_absolute():
            raise PathViolation("Absolute paths are not allowed.")
        candidate = (context.root / requested).resolve(strict=False)
        try:
            candidate.relative_to(context.root.resolve())
        except ValueError as error:
            raise PathViolation("Path escapes the project workspace.") from error
        return candidate

    @staticmethod
    def safe_content_path(context: ProjectContext, relative_path: str) -> Path:
        candidate = WorkspaceManager.safe_path(context, relative_path)
        relative = candidate.relative_to(context.root.resolve())
        if not relative.parts or relative.parts[0] not in {"inputs", "outputs", "work"}:
            raise PathViolation("Tools may only access inputs, outputs, or work.")
        return candidate

    @contextmanager
    def project_lock(self, project_id: str) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(project_id, threading.RLock())
        with lock:
            yield

    def list_project_ids(self) -> list[str]:
        return sorted(path.name for path in self.projects_root.iterdir() if path.is_dir())
