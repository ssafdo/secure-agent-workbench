from __future__ import annotations

import json
import tempfile
import unittest
from argparse import ArgumentTypeError
from pathlib import Path

from scripts.blind_routing_eval import (
    _unit_interval,
    create_manifest,
    evaluate,
    load_dataset,
)


def _case(index: int, task: str | None = None) -> dict[str, object]:
    return {
        "id": f"case-{index:03d}",
        "language": "en" if index % 2 else "zh",
        "category": "evidence" if index % 2 else "synthesis",
        "task": task or ("Find evidence about policy." if index % 2 else "总结所有资料。"),
        "expectedSpecialist": "retrieval" if index % 2 else "synthesis",
        "errorCost": 2,
        "deidentified": True,
        "reviewedByHuman": True,
    }


class BlindRoutingEvalTests(unittest.TestCase):
    def _write_dataset(self, directory: str, cases: list[dict[str, object]]) -> Path:
        path = Path(directory) / "tasks.jsonl"
        path.write_text(
            "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
            encoding="utf-8",
        )
        return path

    def test_sealed_evaluation_never_echoes_task_text(self) -> None:
        private_marker = "policy-phrase-for-local-blind-test"
        cases = [_case(index) for index in range(1, 21)]
        cases[0]["task"] = f"Find evidence about {private_marker}."
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            loaded = load_dataset(dataset)
            manifest = create_manifest(dataset, loaded)
            result = evaluate(dataset, manifest, loaded)

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["cases"], 20)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertNotIn(private_marker, rendered)
        self.assertTrue(all("task" not in item for item in result["caseResults"]))

    def test_rejects_sensitive_data_before_sealing(self) -> None:
        cases = [_case(index) for index in range(1, 21)]
        cases[3]["task"] = "Email the result to private.user@example.com"
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            with self.assertRaisesRegex(ValueError, "email-address"):
                load_dataset(dataset)

    def test_rejects_non_utf8_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "tasks.jsonl"
            dataset.write_bytes(b"\xff\xfe\x00")
            with self.assertRaisesRegex(ValueError, "valid UTF-8"):
                load_dataset(dataset)

    def test_rejects_dataset_changed_after_sealing(self) -> None:
        cases = [_case(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            loaded = load_dataset(dataset)
            manifest = create_manifest(dataset, loaded)
            cases[0]["task"] = "Find evidence about a changed policy."
            dataset = self._write_dataset(directory, cases)
            changed = load_dataset(dataset)
            with self.assertRaisesRegex(ValueError, "changed after it was sealed"):
                evaluate(dataset, manifest, changed)

    def test_requires_explicit_human_review_and_deidentification(self) -> None:
        cases = [_case(index) for index in range(1, 21)]
        cases[0]["reviewedByHuman"] = False
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            with self.assertRaisesRegex(ValueError, "human review"):
                load_dataset(dataset)

    def test_rejects_router_changed_after_sealing(self) -> None:
        cases = [_case(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            loaded = load_dataset(dataset)
            manifest = create_manifest(dataset, loaded)
            manifest["routerSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "routing code changed"):
                evaluate(dataset, manifest, loaded)

    def test_rejects_manifest_distribution_tampering(self) -> None:
        cases = [_case(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._write_dataset(directory, cases)
            loaded = load_dataset(dataset)
            manifest = create_manifest(dataset, loaded)
            manifest["languageCounts"] = {"en": 20}
            with self.assertRaisesRegex(ValueError, "language distribution"):
                evaluate(dataset, manifest, loaded)

    def test_cli_thresholds_must_be_unit_intervals(self) -> None:
        self.assertEqual(_unit_interval("0.8"), 0.8)
        for value in ("-0.1", "1.1", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ArgumentTypeError):
                _unit_interval(value)


if __name__ == "__main__":
    unittest.main()
