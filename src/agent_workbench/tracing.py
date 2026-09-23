from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from .models import ProjectContext


class TraceStore:
    """Writes one append-only JSONL trace per project session."""

    def __init__(self) -> None:
        self._write_lock = Lock()

    def path_for(self, context: ProjectContext) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", context.session_id):
            raise ValueError("session_id contains unsupported characters.")
        return context.root / ".agent" / "traces" / f"{context.session_id}.jsonl"

    def append(self, context: ProjectContext, event: dict[str, Any]) -> None:
        record = {"timestamp": datetime.now(UTC).isoformat(), **event}
        trace_path = self.path_for(context)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False, default=str)
        with self._write_lock:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
