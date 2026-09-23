from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_workbench.models import PathViolation
from agent_workbench.workspace import WorkspaceManager


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceManager(
            Path(self.temp_dir.name), b"test-secret-with-enough-bytes"
        )
        self.context = self.workspace.create_project(
            "research", "user-a", "conversation-a", "session-a"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_id_is_stable_and_scoped(self) -> None:
        first = self.workspace.project_id("research", "user-a", "conversation-a")
        again = self.workspace.project_id("research", "user-a", "conversation-a")
        other = self.workspace.project_id("research", "user-b", "conversation-a")
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertNotIn("user-a", first)

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(PathViolation):
            self.workspace.safe_path(self.context, "../../outside.txt")

    def test_rejects_absolute_path(self) -> None:
        with self.assertRaises(PathViolation):
            self.workspace.safe_path(self.context, str(Path(self.temp_dir.name).resolve()))

    def test_content_path_rejects_internal_agent_directory(self) -> None:
        with self.assertRaises(PathViolation):
            self.workspace.safe_content_path(self.context, ".agent/metadata.json")

    def test_rejects_unsafe_session_id_before_creating_project(self) -> None:
        with self.assertRaises(ValueError):
            self.workspace.create_project(
                "research", "user-a", "conversation-a", "../shared"
            )


if __name__ == "__main__":
    unittest.main()
