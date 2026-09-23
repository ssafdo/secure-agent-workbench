from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_workbench.executor import (
    ContainerConfigurationError,
    ContainerExecutionError,
    ContainerExecutor,
    ContainerLimits,
    ContainerTimeout,
)
from agent_workbench.models import Permission, ProjectContext, ToolStatus
from agent_workbench.runtime import AgentRuntime
from agent_workbench.tools import build_default_registry
from agent_workbench.workspace import WorkspaceManager

PINNED_IMAGE = "example/agent-runtime@sha256:" + "a" * 64
LOCAL_IMAGE_ID = "sha256:" + "b" * 64


class FakeRunner:
    def __init__(self, *, timeout: bool = False, stdout: bytes = b"ok") -> None:
        self.timeout = timeout
        self.stdout = stdout
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(command)
        if self.timeout and command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0, self.stdout, b"")


class ContainerExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceManager(
            Path(self.temp_dir.name), b"test-secret-with-enough-bytes"
        )
        default_context = self.workspace.create_project(
            "container", "user", "conversation", "session"
        )
        self.context = ProjectContext(
            project_id=default_context.project_id,
            session_id=default_context.session_id,
            root=default_context.root,
            allowed_permissions=frozenset(
                {Permission.READ, Permission.WRITE, Permission.EXECUTE}
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_registry_has_no_execution_tool(self) -> None:
        self.assertNotIn(
            "container_exec", {spec.name for spec in build_default_registry().specs()}
        )

    def test_image_must_be_digest_pinned(self) -> None:
        with self.assertRaises(ContainerConfigurationError):
            ContainerExecutor("python:3.13", ["python"])

    def test_accepts_immutable_local_image_id(self) -> None:
        executor = ContainerExecutor(LOCAL_IMAGE_ID, ["agent-runner"])
        self.assertEqual(executor.image, LOCAL_IMAGE_ID)

    def test_rejects_root_container_user(self) -> None:
        with self.assertRaises(ContainerConfigurationError):
            ContainerExecutor(LOCAL_IMAGE_ID, ["agent-runner"], container_user="0:0")

    def test_rejects_shell_string_and_non_allowlisted_executable(self) -> None:
        executor = ContainerExecutor(PINNED_IMAGE, ["python"], runner=FakeRunner())
        with self.assertRaises(ContainerExecutionError):
            executor.execute(self.context, "python -c print(1)")
        with self.assertRaises(ContainerExecutionError):
            executor.execute(self.context, ["sh", "-c", "id"])

    def test_runtime_denies_execute_without_permission_and_without_approval(self) -> None:
        runner = FakeRunner()
        executor = ContainerExecutor(PINNED_IMAGE, ["python"], runner=runner)
        default_context = self.workspace.create_project(
            "container", "user", "no-execute", "session"
        )
        denied_permission = AgentRuntime(
            default_context,
            self.workspace,
            build_default_registry(executor),
        ).call("container_exec", {"argv": ["python", "-V"]}, approved=True)
        denied_approval = AgentRuntime(
            self.context,
            self.workspace,
            build_default_registry(executor),
        ).call("container_exec", {"argv": ["python", "-V"]})
        self.assertEqual(denied_permission.status, ToolStatus.DENIED)
        self.assertEqual(denied_approval.status, ToolStatus.DENIED)
        self.assertEqual(runner.calls, [])

    def test_command_has_isolation_flags_and_only_approved_mounts(self) -> None:
        runner = FakeRunner()
        executor = ContainerExecutor(PINNED_IMAGE, ["python"], runner=runner)
        result = executor.execute(self.context, ["python", "-V"])
        command = runner.calls[0]
        rendered = " ".join(command)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--pull never", rendered)
        self.assertIn("--network none", rendered)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop ALL", rendered)
        self.assertIn("--security-opt no-new-privileges", rendered)
        expected_user = (
            f"{os.getuid()}:{os.getgid()}"
            if hasattr(os, "getuid") and os.getuid() > 0
            else "65532:65532"
        )
        self.assertIn(f"--user {expected_user}", rendered)
        mounts = [command[index + 1] for index, item in enumerate(command) if item == "--mount"]
        self.assertEqual(len(mounts), 3)
        self.assertTrue(any("target=/workspace/inputs,readonly" in item for item in mounts))
        self.assertTrue(any("target=/workspace/work" in item for item in mounts))
        self.assertTrue(any("target=/workspace/outputs" in item for item in mounts))
        self.assertNotIn(".agent", rendered)
        self.assertNotIn("docker.sock", rendered)
        self.assertNotIn("DEEPSEEK", rendered)

    def test_timeout_force_removes_named_container(self) -> None:
        runner = FakeRunner(timeout=True)
        executor = ContainerExecutor(PINNED_IMAGE, ["python"], runner=runner)
        with self.assertRaises(ContainerTimeout):
            executor.execute(self.context, ["python", "-V"])
        self.assertEqual(runner.calls[1][1:3], ["rm", "-f"])
        self.assertEqual(runner.calls[0][4], runner.calls[1][3])

    def test_output_is_truncated_at_configured_limit(self) -> None:
        runner = FakeRunner(stdout=b"123456789")
        executor = ContainerExecutor(
            PINNED_IMAGE,
            ["python"],
            limits=ContainerLimits(max_output_bytes=5),
            runner=runner,
        )
        result = executor.execute(self.context, ["python", "-V"])
        self.assertEqual(result.stdout, "12345")
        self.assertTrue(result.stdout_truncated)


if __name__ == "__main__":
    unittest.main()
