from __future__ import annotations

import json
import unittest

from agent_workbench.modeling import (
    ModelCircuitOpen,
    ModelMessage,
    ModelProviderError,
    RetryableModelProviderError,
    parse_model_response,
)
from agent_workbench.providers import (
    DeepSeekResponsesProvider,
    OpenAIResponsesProvider,
    ReliabilityPolicy,
    ResilientModelProvider,
)
from agent_workbench.tools import build_default_registry


class OpenAIResponsesProviderTests(unittest.TestCase):
    def test_translates_tools_messages_timeout_and_function_call(self) -> None:
        captured = {}

        def transport(url, headers, body, timeout):
            captured.update(
                url=url,
                headers=headers,
                body=json.loads(body.decode("utf-8")),
                timeout=timeout,
            )
            return {
                "output": [
                    {
                        "type": "reasoning",
                        "id": "reasoning-1",
                        "summary": [],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "list_files",
                        "arguments": '{"path":"inputs"}',
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }

        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="test-model",
            base_url="https://example.test/v1/",
            timeout_seconds=7.5,
            transport=transport,
        )
        response = parse_model_response(
            provider.complete(
                (
                    ModelMessage("system", "policy"),
                    ModelMessage("user", "list sources"),
                ),
                build_default_registry().specs(),
            )
        )

        self.assertEqual(captured["url"], "https://example.test/v1/responses")
        self.assertEqual(captured["timeout"], 7.5)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["body"]["input"][0]["role"], "developer")
        self.assertTrue(all(tool["strict"] for tool in captured["body"]["tools"]))
        self.assertEqual(response.tool_calls[0].arguments, {"path": "inputs"})
        self.assertIsNone(response.usage.cost_usd)
        self.assertEqual(response.continuation[0]["type"], "reasoning")

    def test_translates_prior_call_output_and_final_text(self) -> None:
        captured = {}

        def transport(url, headers, body, timeout):
            del url, headers, timeout
            captured["body"] = json.loads(body.decode("utf-8"))
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Finished"}],
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 2},
            }

        provider = OpenAIResponsesProvider(
            api_key="test-key", model="test-model", transport=transport
        )
        response = parse_model_response(
            provider.complete(
                (
                    ModelMessage("user", "list"),
                    ModelMessage(
                        "assistant",
                        json.dumps(
                            {
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "name": "list_files",
                                        "arguments": {"path": "inputs"},
                                    }
                                ]
                            }
                        ),
                    ),
                    ModelMessage(
                        "tool", '{"status":"succeeded"}', tool_call_id="call-1"
                    ),
                ),
                build_default_registry().specs(),
            )
        )

        types = [item.get("type") for item in captured["body"]["input"]]
        self.assertEqual(types, [None, "function_call", "function_call_output"])
        self.assertEqual(response.content, "Finished")

    def test_replays_provider_continuation_before_tool_output(self) -> None:
        captured = {}

        def transport(url, headers, body, timeout):
            del url, headers, timeout
            captured["body"] = json.loads(body.decode("utf-8"))
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Finished"}],
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 2},
            }

        provider = OpenAIResponsesProvider(
            api_key="test-key", model="test-model", transport=transport
        )
        continuation = [
            {"type": "reasoning", "id": "reasoning-1", "summary": []},
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "list_files",
                "arguments": '{"path":"inputs"}',
            },
        ]
        provider.complete(
            (
                ModelMessage("user", "list"),
                ModelMessage(
                    "assistant",
                    json.dumps(
                        {
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "list_files",
                                    "arguments": {"path": "inputs"},
                                }
                            ],
                            "continuation": continuation,
                        }
                    ),
                ),
                ModelMessage("tool", "[]", tool_call_id="call-1"),
            ),
            build_default_registry().specs(),
        )
        types = [item.get("type") for item in captured["body"]["input"]]
        self.assertEqual(
            types, [None, "reasoning", "function_call", "function_call_output"]
        )


class DeepSeekResponsesProviderTests(unittest.TestCase):
    def test_uses_stateless_responses_endpoint_and_parses_tool_usage(self) -> None:
        captured = {}

        def transport(url, headers, body, timeout):
            captured.update(
                url=url,
                headers=headers,
                body=json.loads(body.decode("utf-8")),
                timeout=timeout,
            )
            return {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "deepseek-call-1",
                        "name": "list_files",
                        "arguments": '{"path":"inputs"}',
                    }
                ],
                "usage": {
                    "input_tokens": 31,
                    "output_tokens": 7,
                    "input_tokens_details": {"cached_tokens": 10},
                },
            }

        provider = DeepSeekResponsesProvider(
            api_key="deepseek-test-key",
            model="deepseek-flash",
            transport=transport,
        )
        response = parse_model_response(
            provider.complete(
                (
                    ModelMessage("system", "policy"),
                    ModelMessage("user", "inspect sources"),
                ),
                build_default_registry().specs(),
            )
        )

        self.assertEqual(provider.name, "deepseek-responses")
        self.assertEqual(captured["url"], "https://api.deepseek.com/responses")
        self.assertEqual(
            captured["headers"]["Authorization"], "Bearer deepseek-test-key"
        )
        self.assertEqual(captured["body"]["model"], "deepseek-flash")
        self.assertEqual(captured["body"]["input"][0]["role"], "developer")
        self.assertEqual(response.tool_calls[0].id, "deepseek-call-1")
        self.assertEqual(response.usage.input_tokens, 31)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertIsNone(response.usage.cost_usd)


class _FlakyProvider:
    name = "flaky"

    def __init__(self, failures: int, retryable: bool = True) -> None:
        self.failures = failures
        self.retryable = retryable
        self.calls = 0

    def complete(self, messages, tools):
        del messages, tools
        self.calls += 1
        if self.calls <= self.failures:
            if self.retryable:
                raise RetryableModelProviderError("temporary")
            raise ModelProviderError("permanent")
        return {
            "type": "final",
            "content": "recovered",
            "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": None},
        }


class ResilientModelProviderTests(unittest.TestCase):
    def test_retries_only_retryable_failures_with_bounded_backoff(self) -> None:
        provider = _FlakyProvider(2)
        delays = []
        resilient = ResilientModelProvider(
            provider,
            policy=ReliabilityPolicy(
                max_attempts=3,
                initial_backoff_seconds=0.1,
                max_backoff_seconds=0.15,
            ),
            sleep=delays.append,
        )
        result = resilient.complete((), ())
        self.assertEqual(result["content"], "recovered")
        self.assertEqual(provider.calls, 3)
        self.assertEqual(delays, [0.1, 0.15])

    def test_does_not_retry_permanent_failure(self) -> None:
        provider = _FlakyProvider(1, retryable=False)
        resilient = ResilientModelProvider(provider, sleep=lambda _: None)
        with self.assertRaises(ModelProviderError):
            resilient.complete((), ())
        self.assertEqual(provider.calls, 1)

    def test_opens_circuit_and_allows_probe_after_cooldown(self) -> None:
        now = [10.0]
        provider = _FlakyProvider(4)
        resilient = ResilientModelProvider(
            provider,
            policy=ReliabilityPolicy(
                max_attempts=2,
                initial_backoff_seconds=0,
                max_backoff_seconds=0,
                failure_threshold=2,
                cooldown_seconds=5,
            ),
            clock=lambda: now[0],
            sleep=lambda _: None,
        )
        with self.assertRaises(RetryableModelProviderError):
            resilient.complete((), ())
        with self.assertRaises(RetryableModelProviderError):
            resilient.complete((), ())
        with self.assertRaises(ModelCircuitOpen):
            resilient.complete((), ())
        self.assertEqual(provider.calls, 4)

        now[0] = 15.0
        result = resilient.complete((), ())
        self.assertEqual(result["content"], "recovered")
        self.assertEqual(provider.calls, 5)


if __name__ == "__main__":
    unittest.main()
