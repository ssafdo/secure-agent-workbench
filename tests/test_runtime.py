from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_workbench.agents import ResearchAgent
from agent_workbench.models import ToolStatus, WorkbenchError
from agent_workbench.runtime import AgentRuntime
from agent_workbench.tools import build_default_registry
from agent_workbench.tracing import TraceStore
from agent_workbench.workspace import WorkspaceManager


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceManager(
            Path(self.temp_dir.name), b"test-secret-with-enough-bytes"
        )
        self.context = self.workspace.create_project(
            "research", "user-a", "conversation-a", "session-a"
        )
        self.runtime = AgentRuntime(
            self.context, self.workspace, build_default_registry(), max_steps=10
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_write_requires_explicit_approval(self) -> None:
        denied = self.runtime.call(
            "write_text", {"path": "outputs/no.txt", "content": "no"}
        )
        self.assertEqual(denied.status, ToolStatus.DENIED)
        self.assertFalse((self.context.root / "outputs" / "no.txt").exists())

        allowed = self.runtime.call(
            "write_text",
            {"path": "outputs/yes.txt", "content": "yes"},
            approved=True,
        )
        self.assertEqual(allowed.status, ToolStatus.SUCCEEDED)
        self.assertEqual(
            [event["status"] for event in self.runtime.tool_events],
            ["denied", "succeeded"],
        )

    def test_failed_and_denied_calls_are_traced_without_values(self) -> None:
        secret_value = "private-value-123"
        self.runtime.call(
            "write_text", {"path": "outputs/no.txt", "content": secret_value}
        )
        self.runtime.call("read_text", {"path": "inputs/missing.txt"})
        trace_path = TraceStore().path_for(self.context)
        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([event["status"] for event in events], ["denied", "failed"])
        self.assertEqual(events[0]["argument_keys"], ["content", "path"])
        self.assertNotIn(secret_value, trace_path.read_text(encoding="utf-8"))

    def test_successful_read_content_is_not_written_to_trace(self) -> None:
        secret_value = "source-secret-456"
        source = self.workspace.safe_content_path(self.context, "inputs/private.txt")
        source.write_text(secret_value, encoding="utf-8")
        result = self.runtime.call("read_text", {"path": "inputs/private.txt"})
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        trace_text = TraceStore().path_for(self.context).read_text(encoding="utf-8")
        self.assertNotIn(secret_value, trace_text)

    def test_tools_cannot_access_internal_metadata(self) -> None:
        read = self.runtime.call("read_text", {"path": ".agent/metadata.json"})
        write = self.runtime.call(
            "write_text",
            {"path": ".agent/metadata.json", "content": "tampered"},
            approved=True,
        )
        self.assertEqual(read.status, ToolStatus.FAILED)
        self.assertEqual(write.status, ToolStatus.FAILED)

    def test_agent_cannot_write_to_inputs(self) -> None:
        result = self.runtime.call(
            "write_text",
            {"path": "inputs/injected.txt", "content": "bad"},
            approved=True,
        )
        self.assertEqual(result.status, ToolStatus.FAILED)

    def test_research_agent_creates_report(self) -> None:
        source = self.workspace.safe_content_path(self.context, "inputs/source.md")
        source.write_text("Isolation must be testable.", encoding="utf-8")
        report = ResearchAgent(self.runtime).run("Find priorities", approve_write=True)
        self.assertEqual(report.source_files, ("inputs/source.md",))
        artifact = self.context.root / report.artifact_path
        self.assertIn("Isolation must be testable", artifact.read_text(encoding="utf-8"))

    def test_research_agent_refuses_unapproved_artifact(self) -> None:
        with self.assertRaises(WorkbenchError):
            ResearchAgent(self.runtime).run("Find priorities", approve_write=False)


if __name__ == "__main__":
    unittest.main()
