from __future__ import annotations

import argparse
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_workbench.cli import _hosted_provider, smoke_container
from agent_workbench.executor import ContainerResult
from agent_workbench.providers import (
    DeepSeekResponsesProvider,
    OpenAIResponsesProvider,
)


class HostedProviderConfigurationTests(unittest.TestCase):
    def test_no_generic_configuration_keeps_hosted_disabled(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(_hosted_provider())

    def test_builds_deepseek_provider_from_dedicated_server_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_WORKBENCH_MODEL_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "server-secret",
                "DEEPSEEK_MODEL": "deepseek-flash",
                "DEEPSEEK_BASE_URL": "https://gateway.deepseek.test",
                "AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS": "12",
            },
            clear=True,
        ):
            resilient = _hosted_provider()

        self.assertIsNotNone(resilient)
        provider = resilient.provider
        self.assertIsInstance(provider, DeepSeekResponsesProvider)
        self.assertEqual(provider.name, "deepseek-responses")
        self.assertEqual(provider.model, "deepseek-flash")
        self.assertEqual(provider.base_url, "https://gateway.deepseek.test")
        self.assertEqual(provider.timeout_seconds, 12)

    def test_deepseek_requires_key_and_explicit_model(self) -> None:
        with patch.dict(
            "os.environ",
            {"AGENT_WORKBENCH_MODEL_PROVIDER": "deepseek"},
            clear=True,
        ):
            with self.assertRaises(SystemExit):
                _hosted_provider()

    def test_existing_responses_configuration_remains_compatible(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_WORKBENCH_MODEL_API_KEY": "generic-key",
                "AGENT_WORKBENCH_MODEL": "generic-model",
            },
            clear=True,
        ):
            resilient = _hosted_provider()

        self.assertIsNotNone(resilient)
        self.assertIsInstance(resilient.provider, OpenAIResponsesProvider)

    def test_rejects_unknown_provider_kind(self) -> None:
        with patch.dict(
            "os.environ",
            {"AGENT_WORKBENCH_MODEL_PROVIDER": "arbitrary-proxy"},
            clear=True,
        ):
            with self.assertRaises(SystemExit):
                _hosted_provider()


class FakeSmokeExecutor:
    def execute(self, context, argv):
        self.argv = argv
        (context.root / "outputs" / "container-smoke.txt").write_text(
            "isolated:phase-8-real", encoding="utf-8"
        )
        return ContainerResult(
            exit_code=0,
            stdout="container-smoke-ok\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class ContainerSmokeCommandTests(unittest.TestCase):
    def test_smoke_reports_structured_success(self) -> None:
        facts = {
            "dockerCliPresent": True,
            "daemonReachable": True,
            "imageConfigured": True,
            "imageDigestPinned": True,
            "imageAvailableLocally": True,
            "allowlistConfigured": True,
            "executorEnabled": True,
            "ready": True,
            "image": "sha256:" + "a" * 64,
        }
        output = io.StringIO()
        with (
            patch(
                "agent_workbench.cli._container_environment",
                return_value=(True, facts["image"], ("agent-runner",), "docker"),
            ),
            patch("agent_workbench.cli.container_doctor", return_value=facts),
            patch(
                "agent_workbench.cli._container_executor",
                return_value=FakeSmokeExecutor(),
            ),
            patch(
                "agent_workbench.cli.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ),
            redirect_stdout(output),
        ):
            exit_code = smoke_container(argparse.Namespace())

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifact"], "isolated:phase-8-real")
        self.assertEqual(payload["traceEvents"], 1)
        self.assertEqual(payload["residualContainers"], [])

if __name__ == "__main__":
    unittest.main()
