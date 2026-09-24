from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.blind_routing_adjudicate import load_candidates
from scripts.blind_routing_intake import IntakeState, collect_candidates, create_server


class BlindRoutingIntakeTests(unittest.TestCase):
    def _temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        private_root = Path("benchmarks/private")
        private_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=private_root)

    def _write_intake(self, directory: str, cases: int = 21) -> Path:
        path = Path(directory) / "batch-2-intake.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "id": f"b2-case-{index:03d}",
                        "language": "en" if index % 2 else "zh",
                        "task": f"Find the documented retention rule for case {index}.",
                        "sourceRow": 900_000 + index,
                    }
                )
                for index in range(cases)
            )
            + "\n",
            encoding="utf-8",
        )
        return path

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
            with self.assertRaisesRegex(ValueError, "At least 20"):
                state.save({"id": state.cases[-1]["id"], "decision": "approve", "task": state.cases[-1]["task"]})
            self.assertNotIn(state.cases[-1]["id"], state.reviews)
            self.assertFalse(state.output_path.exists())

    def test_collector_pins_revision_excludes_previous_rows_and_prints_no_tasks(self) -> None:
        with self._temporary_directory() as directory:
            output = Path(directory) / "batch-2-intake.jsonl"
            previous = Path(directory) / "previous.json"
            previous.write_text(json.dumps({"cases": [{"sourceRow": 800_000}]}), encoding="utf-8")

            def fetch(url: str) -> object:
                if "/api/datasets/" in url:
                    return {"sha": "7d6490e462285cf85d91eabea0f9a954fbddcd1f"}
                rows = []
                for index, language in enumerate(("English", "English", "Chinese")):
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

            summary = collect_candidates(output, previous, 800_000, 1, 1, fetch)
            self.assertEqual(summary["languages"], {"en": 1, "zh": 1})
            self.assertFalse(summary["taskTextPrinted"])
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertNotIn(800_000, {row["sourceRow"] for row in rows})

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


if __name__ == "__main__":
    unittest.main()
