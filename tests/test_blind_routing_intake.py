from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from scripts.blind_routing_adjudicate import load_candidates
from scripts.blind_routing_intake import (
    IntakeState,
    _fetch_json,
    collect_candidates,
    combine_completed_reviews,
    create_server,
    translate_intake,
)


class BlindRoutingIntakeTests(unittest.TestCase):
    def _temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        private_root = Path("benchmarks/private")
        private_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=private_root)

    def _write_intake(
        self,
        directory: str,
        cases: int = 21,
        prefix: str = "b2-case",
        source_start: int = 900_000,
    ) -> Path:
        path = Path(directory) / "batch-2-intake.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "id": f"{prefix}-{index:03d}",
                        "language": "en" if index % 2 else "zh",
                        "task": f"Find the documented retention rule for {prefix} case {index}.",
                        "sourceRow": source_start + index,
                    }
                )
                for index in range(cases)
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_fetch_json_retries_transient_connection_failure(self) -> None:
        response = io.BytesIO(json.dumps({"ok": True}).encode("utf-8"))
        response.status = 200
        with (
            patch(
                "scripts.blind_routing_intake.urlopen",
                side_effect=[URLError("temporary disconnect"), response],
            ) as open_url,
            patch("scripts.blind_routing_intake.sleep") as pause,
        ):
            result = _fetch_json("https://example.invalid/dataset")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(open_url.call_count, 2)
        pause.assert_called_once_with(1)

    def test_review_requires_every_decision_then_writes_human_reviewed_candidates(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory)
            output = Path(directory) / "batch-2-candidates.jsonl"
            provenance = Path(directory) / "batch-2-provenance.json"
            state = IntakeState(intake, output, provenance, minimum_approved=20)
            for index, case in enumerate(state.cases):
                result = state.save(
                    {
                        "id": case["id"],
                        "decision": "exclude" if index == 0 else "approve",
                        "task": case["task"],
                    }
                )
            self.assertTrue(result["finalized"])
            self.assertEqual(result["approved"], 20)
            self.assertEqual(len(load_candidates(output)), 20)
            metadata = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertTrue(metadata["selection"]["humanReviewCompleted"])
            self.assertEqual(metadata["selection"]["excludedCases"], 1)
            self.assertFalse(state.draft_path.exists())

    def test_sensitive_approved_text_is_rejected_without_changing_draft(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory)
            state = IntakeState(
                intake,
                Path(directory) / "batch-2-candidates.jsonl",
                Path(directory) / "batch-2-provenance.json",
            )
            with self.assertRaisesRegex(ValueError, "sensitive-data"):
                state.save(
                    {
                        "id": state.cases[0]["id"],
                        "decision": "approve",
                        "task": "Use API key: sk-this-is-a-sensitive-test-value in the request.",
                    }
                )
            self.assertFalse(state.draft_path.exists())

    def test_complete_review_cannot_finalize_below_minimum(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory, cases=20)
            state = IntakeState(
                intake,
                Path(directory) / "batch-2-candidates.jsonl",
                Path(directory) / "batch-2-provenance.json",
            )
            for case in state.cases[:-1]:
                state.save({"id": case["id"], "decision": "exclude", "task": case["task"]})
            result = state.save(
                {
                    "id": state.cases[-1]["id"],
                    "decision": "approve",
                    "task": state.cases[-1]["task"],
                }
            )
            self.assertTrue(result["insufficient"])
            self.assertEqual(result["shortfall"], 19)
            self.assertIn(state.cases[-1]["id"], state.reviews)
            self.assertTrue(state.draft_path.exists())
            self.assertFalse(state.output_path.exists())

    def test_collector_pins_revision_excludes_previous_rows_and_prints_no_tasks(self) -> None:
        with self._temporary_directory() as directory:
            output = Path(directory) / "batch-2-intake.jsonl"
            previous = Path(directory) / "previous.json"
            previous.write_text(json.dumps({"cases": [{"sourceRow": 800_000}]}), encoding="utf-8")
            excluded_intake = Path(directory) / "excluded-intake.jsonl"
            excluded_intake.write_text(
                json.dumps(
                    {
                        "id": "prior-case",
                        "language": "en",
                        "task": "Review the prior sample.",
                        "sourceRow": 800_001,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            def fetch(url: str) -> object:
                if "/api/datasets/" in url:
                    return {"sha": "7d6490e462285cf85d91eabea0f9a954fbddcd1f"}
                rows = []
                for index, language in enumerate(("English", "English", "English", "Chinese")):
                    rows.append(
                        {
                            "row_idx": 800_000 + index,
                            "row": {
                                "language": language,
                                "toxic": False,
                                "redacted": False,
                                "conversation": [
                                    {
                                        "role": "user",
                                        "content": f"Explain the documented policy for sample {index}.",
                                        "toxic": False,
                                        "redacted": False,
                                    }
                                ],
                            },
                        }
                    )
                return {"rows": rows}

            summary = collect_candidates(
                output,
                previous,
                800_000,
                1,
                1,
                fetch,
                exclude_intakes=(excluded_intake,),
            )
            self.assertEqual(summary["languages"], {"en": 1, "zh": 1})
            self.assertEqual(summary["excludedSourceRows"], 2)
            self.assertFalse(summary["taskTextPrinted"])
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertTrue({800_000, 800_001}.isdisjoint({row["sourceRow"] for row in rows}))

    def test_research_domain_filter_skips_unrelated_prompts(self) -> None:
        with self._temporary_directory() as directory:
            output = Path(directory) / "research-intake.jsonl"

            def fetch(url: str) -> object:
                if "/api/datasets/" in url:
                    return {"sha": "7d6490e462285cf85d91eabea0f9a954fbddcd1f"}
                return {
                    "rows": [
                        {
                            "row_idx": 810_000,
                            "row": {
                                "language": "English",
                                "toxic": False,
                                "redacted": False,
                                "conversation": [{"role": "user", "content": "Write a limerick about rain.", "toxic": False, "redacted": False}],
                            },
                        },
                        {
                            "row_idx": 810_001,
                            "row": {
                                "language": "English",
                                "toxic": False,
                                "redacted": False,
                                "conversation": [{"role": "user", "content": "Summarize the attached research notes.", "toxic": False, "redacted": False}],
                            },
                        },
                        {
                            "row_idx": 810_002,
                            "row": {
                                "language": "Chinese",
                                "toxic": False,
                                "redacted": False,
                                "conversation": [{"role": "user", "content": "请比较两份研究报告的结论。", "toxic": False, "redacted": False}],
                            },
                        },
                    ]
                }

            summary = collect_candidates(output, None, 810_000, 1, 1, fetch, research_only=True)
            self.assertTrue(summary["researchDomainFilter"])
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["sourceRow"] for row in rows}, {810_001, 810_002})

    def test_combines_complete_review_drafts_without_rewriting_them(self) -> None:
        with self._temporary_directory() as directory:
            root = Path(directory)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = IntakeState(
                self._write_intake(str(first_dir), 12, "first", 820_000),
                first_dir / "candidates.jsonl",
                first_dir / "provenance.json",
                minimum_approved=1,
                defer_finalization=True,
            )
            second = IntakeState(
                self._write_intake(str(second_dir), 12, "second", 830_000),
                second_dir / "candidates.jsonl",
                second_dir / "provenance.json",
                minimum_approved=1,
                defer_finalization=True,
            )
            for index, case in enumerate(first.cases):
                result = first.save(
                    {
                        "id": case["id"],
                        "decision": "approve" if index < 10 else "exclude",
                        "task": case["task"],
                    }
                )
            self.assertTrue(result["readyToCombine"])
            for case in second.cases[:10]:
                result = second.save(
                    {"id": case["id"], "decision": "approve", "task": case["task"]}
                )
            self.assertTrue(result["readyToCombine"])
            self.assertTrue(first.draft_path.exists())
            self.assertTrue(second.draft_path.exists())

            insufficient_output = root / "insufficient-candidates.jsonl"
            insufficient_provenance = root / "insufficient-provenance.json"
            with self.assertRaisesRegex(ValueError, "current reviewed batches contain 10"):
                combine_completed_reviews(
                    [(first.intake_path, first.draft_path)],
                    insufficient_output,
                    insufficient_provenance,
                )
            self.assertFalse(insufficient_output.exists())
            self.assertFalse(insufficient_provenance.exists())

            output = root / "combined-candidates.jsonl"
            provenance = root / "combined-provenance.json"
            with self.assertRaisesRegex(ValueError, "Every intake case"):
                combine_completed_reviews(
                    [
                        (first.intake_path, first.draft_path),
                        (second.intake_path, second.draft_path),
                    ],
                    output,
                    provenance,
                )
            summary = combine_completed_reviews(
                [
                    (first.intake_path, first.draft_path),
                    (second.intake_path, second.draft_path),
                ],
                output,
                provenance,
                allow_prefix_stop=True,
            )
            self.assertEqual(summary["approvedCases"], 20)
            self.assertEqual(summary["unreviewedCases"], 2)
            self.assertEqual(len(load_candidates(output)), 20)
            self.assertTrue(first.draft_path.exists())
            self.assertTrue(second.draft_path.exists())
            metadata = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertEqual(len(metadata["reviewedBatches"]), 2)
            self.assertTrue(metadata["selection"]["sequentialPrefixStop"])

    def test_deferred_review_can_stop_at_threshold_but_not_with_gaps(self) -> None:
        with self._temporary_directory() as directory:
            root = Path(directory)
            state = IntakeState(
                self._write_intake(directory, 5),
                root / "candidates.jsonl",
                root / "provenance.json",
                minimum_approved=2,
                defer_finalization=True,
            )
            first = state.cases[0]
            third = state.cases[2]
            state.save({"id": first["id"], "decision": "approve", "task": first["task"]})
            result = state.save({"id": third["id"], "decision": "approve", "task": third["task"]})
            self.assertTrue(result["readyToCombine"])
            with self.assertRaisesRegex(ValueError, "continuous prefix"):
                combine_completed_reviews(
                    [(state.intake_path, state.draft_path)],
                    root / "combined.jsonl",
                    root / "combined-provenance.json",
                    minimum_approved=2,
                    allow_prefix_stop=True,
                )

    def test_session_includes_advisory_without_changing_review_decisions(self) -> None:
        with self._temporary_directory() as directory:
            state = IntakeState(
                self._write_intake(directory),
                Path(directory) / "candidates.jsonl",
                Path(directory) / "provenance.json",
            )
            recommendation = state.session()["cases"][0]["recommendation"]
            self.assertEqual(set(recommendation), {"level", "label", "reason"})
            self.assertEqual(state.reviews, {})

    def test_paths_outside_repository_private_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            intake = self._write_intake(directory)
            with self.assertRaisesRegex(ValueError, "private directory"):
                IntakeState(
                    intake,
                    Path(directory) / "candidates.jsonl",
                    Path(directory) / "provenance.json",
                )

    def test_server_rejects_non_loopback_binding(self) -> None:
        with self._temporary_directory() as directory:
            state = IntakeState(
                self._write_intake(directory),
                Path(directory) / "candidates.jsonl",
                Path(directory) / "provenance.json",
            )
            with self.assertRaisesRegex(ValueError, "loopback"):
                create_server(state, "0.0.0.0")

    def test_existing_final_outputs_are_never_overwritten(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory)
            output = Path(directory) / "candidates.jsonl"
            provenance = Path(directory) / "provenance.json"
            output.write_text("existing\n", encoding="utf-8")
            provenance.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already finalized"):
                IntakeState(intake, output, provenance)

    def test_translation_aids_are_hash_bound_and_never_enter_candidates(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory)
            translation_path = Path(directory) / "translations.json"

            class Provider:
                def complete(self, messages: object, tools: object) -> dict[str, object]:
                    return {
                        "type": "final",
                        "content": json.dumps({"text": "辅助译文"}, ensure_ascii=False),
                        "usage": {"input_tokens": 10, "output_tokens": 3, "cost_usd": None},
                    }

            summary = translate_intake(intake, translation_path, Provider(), "test-model")
            self.assertEqual(summary["translations"], 21)
            stored = json.loads(translation_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["translations"][0]["text"], "辅助译文")
            state = IntakeState(
                intake,
                Path(directory) / "candidates.jsonl",
                Path(directory) / "provenance.json",
                translations_path=translation_path,
            )
            self.assertEqual(state.session()["cases"][0]["translation"], "辅助译文")
            for case in state.cases:
                state.save({"id": case["id"], "decision": "approve", "task": case["task"]})
            self.assertNotIn("辅助译文", state.output_path.read_text(encoding="utf-8"))

    def test_translation_file_must_match_intake_hash(self) -> None:
        with self._temporary_directory() as directory:
            intake = self._write_intake(directory)
            translation_path = Path(directory) / "translations.json"
            translation_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "kind": "secure-agent-workbench/blind-routing-intake-translations",
                        "intakeSha256": "0" * 64,
                        "provider": "deepseek",
                        "model": "test",
                        "createdAt": "2026-09-24T00:00:00Z",
                        "translations": [],
                        "usage": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "metadata"):
                IntakeState(
                    intake,
                    Path(directory) / "candidates.jsonl",
                    Path(directory) / "provenance.json",
                    translations_path=translation_path,
                )


if __name__ == "__main__":
    unittest.main()
