from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_workbench.conversation import ContextBudget, estimate_context_tokens
from agent_workbench.modeling import ModelMessage
from agent_workbench.sessions import SessionConflict, SessionExpired, SessionStore
from agent_workbench.workspace import WorkspaceManager


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceManager(
            Path(self.temp_dir.name), b"test-secret-with-enough-bytes"
        )
        self.context = self.workspace.create_project(
            "research-api", "local-client", "session-a", "session-a"
        )
        self.current_time = datetime(2026, 9, 22, tzinfo=UTC)
        self.store = SessionStore(
            ttl_seconds=60,
            context_budget=ContextBudget(
                max_estimated_tokens=220,
                preserve_recent=2,
                summary_max_tokens=48,
            ),
            now=lambda: self.current_time,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_saves_atomically_and_rejects_stale_version(self) -> None:
        empty = self.store.load(self.context, 0)
        saved = self.store.save(
            self.context,
            empty,
            (ModelMessage("user", "first"), ModelMessage("assistant", "answer")),
        )

        self.assertEqual(saved.version, 1)
        self.assertEqual(self.store.load(self.context, 1).history, saved.history)
        with self.assertRaises(SessionConflict):
            self.store.load(self.context, 0)

        payload = json.loads(
            self.store.path_for(self.context).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["version"], 1)

    def test_bounds_persisted_history(self) -> None:
        empty = self.store.load(self.context, 0)
        saved = self.store.save(
            self.context,
            empty,
            (
                ModelMessage("user", "old fact " * 100),
                ModelMessage("assistant", "old response " * 100),
                ModelMessage("user", "latest-user-fact"),
                ModelMessage("assistant", "latest-assistant-fact"),
            ),
        )

        measured = estimate_context_tokens(
            (ModelMessage("system", "Persisted session context."), *saved.history)
        )
        self.assertLessEqual(measured, 220)
        self.assertEqual(saved.history[-2].content, "latest-user-fact")
        self.assertEqual(saved.history[-1].content, "latest-assistant-fact")

    def test_expired_session_is_deleted(self) -> None:
        empty = self.store.load(self.context, 0)
        self.store.save(
            self.context,
            empty,
            (ModelMessage("user", "expires"),),
        )
        self.current_time += timedelta(seconds=61)

        with self.assertRaises(SessionExpired):
            self.store.load(self.context, 1)
        self.assertFalse(self.store.path_for(self.context).exists())


if __name__ == "__main__":
    unittest.main()
