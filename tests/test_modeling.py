from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_workbench.conversation import ContextBudget, estimate_context_tokens
from agent_workbench.modeling import (
    ModelBudget,
    ModelBudgetExceeded,
    ModelLoopLimitExceeded,
    ModelMessage,
    ModelProtocolError,
    ScriptedModelProvider,
    parse_model_response,
)
from agent_workbench.react import ReActAgent
from agent_workbench.runtime import AgentRuntime
from agent_workbench.tools import build_default_registry
from agent_workbench.workspace import WorkspaceManager


def usage(input_tokens: int = 0, output_tokens: int = 0) -> dict[str, int | float]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": 0.0,
    }


class ModelProtocolTests(unittest.TestCase):
    def test_rejects_non_object_tool_arguments(self) -> None:
        with self.assertRaises(ModelProtocolError):
            parse_model_response(
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "call-1", "name": "read_text", "arguments": "{}"}
                    ],
                    "usage": usage(),
                }
            )

    def test_rejects_duplicate_tool_call_ids(self) -> None:
        with self.assertRaises(ModelProtocolError):
            parse_model_response(
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "same", "name": "list_files", "arguments": {}},
                        {"id": "same", "name": "read_text", "arguments": {}},
                    ],
                    "usage": usage(),
                }
            )


class ReActAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = WorkspaceManager(
            Path(self.temp_dir.name), b"test-secret-with-enough-bytes"
        )
        self.context = self.workspace.create_project(
            "react", "user-a", "conversation-a", "session-a"
        )
        self.runtime = AgentRuntime(
            self.context, self.workspace, build_default_registry(), max_steps=8
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_executes_structured_calls_through_runtime(self) -> None:
        provider = ScriptedModelProvider(
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "write-1",
                            "name": "write_text",
                            "arguments": {
                                "path": "outputs/result.txt",
                                "content": "complete",
                            },
                        }
                    ],
                    "usage": usage(10, 4),
                },
                {
                    "type": "final",
                    "content": "Done",
                    "data": {"artifactPath": "outputs/result.txt"},
                    "usage": usage(5, 2),
                },
            ]
        )
        result = ReActAgent(self.runtime, provider).run(
            "Write the result", approve_write=True
        )
        self.assertEqual(result.content, "Done")
        self.assertEqual(result.usage["calls"], 2)
        self.assertEqual(result.usage["inputTokens"], 15)
        self.assertEqual(
            (self.context.root / "outputs" / "result.txt").read_text(encoding="utf-8"),
            "complete",
        )
        self.assertEqual(self.runtime.tool_events[0]["status"], "succeeded")
        self.assertEqual(len(self.runtime.model_events), 2)

    def test_unknown_tool_is_observable_and_returned_to_model(self) -> None:
        provider = ScriptedModelProvider(
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "bad-1", "name": "shell", "arguments": {}}
                    ],
                    "usage": usage(),
                },
                {"type": "final", "content": "Recovered", "usage": usage()},
            ]
        )
        result = ReActAgent(self.runtime, provider).run("Try a tool")
        self.assertEqual(result.content, "Recovered")
        self.assertEqual(self.runtime.tool_events[0]["tool"], "shell")
        self.assertEqual(self.runtime.tool_events[0]["status"], "failed")

    def test_unapproved_model_write_is_denied(self) -> None:
        provider = ScriptedModelProvider(
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "write-1",
                            "name": "write_text",
                            "arguments": {
                                "path": "outputs/denied.txt",
                                "content": "blocked",
                            },
                        }
                    ],
                    "usage": usage(),
                },
                {"type": "final", "content": "Write was denied", "usage": usage()},
            ]
        )
        ReActAgent(self.runtime, provider).run("Write without approval")
        self.assertEqual(self.runtime.tool_events[0]["status"], "denied")
        self.assertEqual(self.runtime.reflection_events, [])
        self.assertFalse((self.context.root / "outputs" / "denied.txt").exists())

    def test_compacts_history_and_preserves_latest_tool_facts(self) -> None:
        provider = ScriptedModelProvider(
            [{"type": "final", "content": "Used latest facts", "usage": usage()}]
        )
        history = (
            ModelMessage("user", "old-user-fact " * 80),
            ModelMessage("assistant", "old-assistant-fact " * 80),
            ModelMessage(
                "assistant",
                '{"tool_calls":[{"id":"fact-1","name":"read_text",'
                '"arguments":{"path":"inputs/latest.txt"}}]}',
            ),
            ModelMessage(
                "tool", "latest-tool-fact=blue", tool_call_id="fact-1"
            ),
        )

        result = ReActAgent(
            self.runtime,
            provider,
            context_budget=ContextBudget(
                max_estimated_tokens=220,
                preserve_recent=3,
                summary_max_tokens=48,
            ),
        ).run("latest-user-fact=approved", history=history)

        sent = provider.requests[0]
        self.assertLessEqual(estimate_context_tokens(sent), 220)
        self.assertTrue(any("Compacted conversation summary" in m.content for m in sent))
        self.assertTrue(any(m.content == "latest-tool-fact=blue" for m in sent))
        self.assertTrue(any(m.content == "latest-user-fact=approved" for m in sent))
        self.assertTrue(result.context["compacted"])
        self.assertGreater(result.context["compactedMessages"], 0)
        self.assertEqual(len(self.runtime.context_events), 1)

    def test_protocol_failure_reflects_once_and_reports_unknown_cost(self) -> None:
        provider = ScriptedModelProvider(
            [
                {"type": "final", "content": "missing usage"},
                {"type": "final", "content": "Recovered", "usage": usage()},
            ]
        )

        result = ReActAgent(self.runtime, provider).run("Recover safely")

        self.assertEqual(result.content, "Recovered")
        self.assertEqual(result.usage["calls"], 2)
        self.assertIsNone(result.usage["inputTokens"])
        self.assertIsNone(result.usage["outputTokens"])
        self.assertIsNone(result.usage["costUSD"])
        self.assertEqual(len(self.runtime.reflection_events), 1)
        self.assertEqual(self.runtime.reflection_events[0]["trigger"], "protocol")
        self.assertNotIn("missing usage", str(self.runtime.reflection_events))

    def test_oversized_latest_tool_result_keeps_head_and_tail_as_json(self) -> None:
        provider = ScriptedModelProvider(
            [{"type": "final", "content": "Read bounded result", "usage": usage()}]
        )
        history = (
            ModelMessage(
                "assistant",
                '{"tool_calls":[{"id":"large-1","name":"read_text",'
                '"arguments":{"path":"inputs/large.txt"}}]}',
            ),
            ModelMessage(
                "tool",
                '{"status":"succeeded","output":"HEAD-FACT '
                + ("detail " * 500)
                + ' TAIL-FACT","error":null}',
                tool_call_id="large-1",
            ),
        )

        result = ReActAgent(
            self.runtime,
            provider,
            context_budget=ContextBudget(
                max_estimated_tokens=220,
                preserve_recent=3,
                summary_max_tokens=32,
            ),
        ).run("Use the latest tool facts", history=history)

        tool_message = next(m for m in provider.requests[0] if m.role == "tool")
        parsed = json.loads(tool_message.content)
        self.assertIn("HEAD-FACT", parsed["output"])
        self.assertIn("TAIL-FACT", parsed["output"])
        self.assertIn("context truncated", parsed["output"])
        self.assertGreater(result.context["truncatedMessages"], 0)

    def test_protocol_failure_cannot_bypass_model_call_budget(self) -> None:
        provider = ScriptedModelProvider(
            [{"type": "final", "content": "missing usage"}]
        )

        with self.assertRaises(ModelProtocolError):
            ReActAgent(
                self.runtime,
                provider,
                budget=ModelBudget(max_calls=1),
            ).run("Do not exceed the call budget")

        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.runtime.reflection_events, [])

    def test_reflection_cannot_bypass_tool_step_budget(self) -> None:
        runtime = AgentRuntime(
            self.context, self.workspace, build_default_registry(), max_steps=1
        )
        provider = ScriptedModelProvider(
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "bad-1", "name": "shell", "arguments": {}}],
                    "usage": usage(),
                },
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "name": "list_files",
                            "arguments": {"path": "inputs"},
                        }
                    ],
                    "usage": usage(),
                },
                {"type": "final", "content": "Stopped", "usage": usage()},
            ]
        )

        ReActAgent(runtime, provider).run("Try one correction")

        self.assertEqual([e["status"] for e in runtime.tool_events], ["failed", "failed"])
        self.assertEqual(runtime.tool_events[1]["error_type"], "StepBudgetExceeded")
        self.assertEqual(len(runtime.reflection_events), 1)
        self.assertEqual(runtime.steps, 1)

    def test_stops_an_infinite_tool_loop(self) -> None:
        repeated = {
            "type": "tool_calls",
            "tool_calls": [
                {
                    "id": "list-1",
                    "name": "list_files",
                    "arguments": {"path": "inputs"},
                }
            ],
            "usage": usage(),
        }
        provider = ScriptedModelProvider([repeated, repeated])
        with self.assertRaises(ModelLoopLimitExceeded):
            ReActAgent(self.runtime, provider, max_turns=2).run("Never finish")

    def test_rejects_observed_usage_over_budget(self) -> None:
        provider = ScriptedModelProvider(
            [{"type": "final", "content": "Too expensive", "usage": usage(11, 0)}]
        )
        with self.assertRaises(ModelBudgetExceeded):
            ReActAgent(
                self.runtime,
                provider,
                budget=ModelBudget(max_calls=2, max_input_tokens=10),
            ).run("Stay within budget")
        self.assertEqual(self.runtime.model_events[0]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
