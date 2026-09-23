from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from .conversation import ContextBudget, ConversationHistory
from .modeling import ModelMessage
from .models import ProjectContext, WorkbenchError


class SessionConflict(WorkbenchError):
    """Raised when optimistic session version validation fails."""


class SessionExpired(WorkbenchError):
    """Raised when a persisted session has exceeded its TTL."""


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    version: int
    expires_at: datetime
    history: tuple[ModelMessage, ...]

    def response(self) -> dict[str, str | int]:
        return {
            "id": self.session_id,
            "version": self.version,
            "expiresAt": self.expires_at.isoformat(),
        }


class SessionStore:
    """Persists bounded conversation state with optimistic version checks."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 86_400,
        context_budget: ContextBudget | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive.")
        self.ttl_seconds = ttl_seconds
        self.context_budget = context_budget or ContextBudget()
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def validate_id(session_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
            raise ValueError("sessionId contains unsupported characters.")
        return session_id

    def path_for(self, context: ProjectContext) -> Path:
        self.validate_id(context.session_id)
        path = context.root / ".agent" / "sessions" / f"{context.session_id}.json"
        try:
            path.resolve(strict=False).relative_to(context.root.resolve())
        except ValueError as error:
            raise ValueError("Session path escapes the project workspace.") from error
        return path

    def load(self, context: ProjectContext, expected_version: int) -> SessionRecord:
        self._validate_version(expected_version)
        path = self.path_for(context)
        if not path.exists():
            if expected_version != 0:
                raise SessionConflict(
                    f"Session version conflict: expected {expected_version}, current 0."
                )
            return SessionRecord(
                context.session_id,
                0,
                self._now() + timedelta(seconds=self.ttl_seconds),
                (),
            )

        record = self._decode(path, context.session_id)
        if record.expires_at <= self._now():
            path.unlink(missing_ok=True)
            raise SessionExpired("Session expired; restart it with expectedVersion 0.")
        if record.version != expected_version:
            raise SessionConflict(
                "Session version conflict: "
                f"expected {expected_version}, current {record.version}."
            )
        return record

    def save(
        self,
        context: ProjectContext,
        current: SessionRecord,
        history: tuple[ModelMessage, ...],
    ) -> SessionRecord:
        path = self.path_for(context)
        if path.exists():
            disk_version = self._decode(path, context.session_id).version
        else:
            disk_version = 0
        if disk_version != current.version:
            raise SessionConflict(
                "Session changed before commit: "
                f"expected {current.version}, current {disk_version}."
            )

        bounded = self._bounded(history)
        saved = SessionRecord(
            context.session_id,
            current.version + 1,
            self._now() + timedelta(seconds=self.ttl_seconds),
            bounded,
        )
        payload = {
            "schemaVersion": 1,
            "sessionId": saved.session_id,
            "version": saved.version,
            "expiresAt": saved.expires_at.isoformat(),
            "history": [
                {
                    "role": message.role,
                    "content": message.content,
                    "toolCallId": message.tool_call_id,
                }
                for message in saved.history
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return saved

    def _bounded(
        self, history: tuple[ModelMessage, ...]
    ) -> tuple[ModelMessage, ...]:
        snapshot = ConversationHistory(
            (ModelMessage("system", "Persisted session context."), *history),
            self.context_budget,
        ).snapshot()
        return snapshot.messages[1:]

    @staticmethod
    def _validate_version(version: int) -> None:
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("expectedVersion must be a non-negative integer.")

    @staticmethod
    def _decode(path: Path, session_id: str) -> SessionRecord:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schemaVersion") != 1
                or payload.get("sessionId") != session_id
            ):
                raise ValueError
            version = payload["version"]
            expires_at = datetime.fromisoformat(payload["expiresAt"])
            raw_history = payload["history"]
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
                or expires_at.tzinfo is None
                or not isinstance(raw_history, list)
            ):
                raise ValueError
            history: list[ModelMessage] = []
            for item in raw_history:
                if not isinstance(item, dict) or set(item) != {
                    "role",
                    "content",
                    "toolCallId",
                }:
                    raise ValueError
                role = item["role"]
                content = item["content"]
                tool_call_id = item["toolCallId"]
                if (
                    role not in {"system", "user", "assistant", "tool"}
                    or not isinstance(content, str)
                    or (tool_call_id is not None and not isinstance(tool_call_id, str))
                ):
                    raise ValueError
                history.append(ModelMessage(role, content, tool_call_id))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise WorkbenchError("Stored session record is invalid.") from error
        return SessionRecord(session_id, version, expires_at, tuple(history))
