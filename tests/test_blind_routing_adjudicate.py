from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.blind_routing_adjudicate import (
    _require_private_path,
    build_consensus_dataset,
    compare_annotations,
    load_annotations,
    load_candidates,
)
from scripts.blind_routing_eval import load_dataset


def _candidate(index: int, marker: str = "") -> dict[str, object]:
    return {
        "id": f"case-{index:03d}",
        "language": "en" if index % 2 else "zh",
        "task": (
            f"Find evidence about policy {marker}."
            if index % 2
            else f"总结所有资料 {marker}。"
        ),
        "deidentified": True,
        "reviewedByHuman": True,
    }


def _annotation(
    reviewer: str,
    cases: list[dict[str, object]],
    candidate_sha256: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "kind": "secure-agent-workbench/blind-routing-annotations",
        "candidateSha256": candidate_sha256,
        "reviewerId": reviewer,
        "labels": [
            {
                "id": case["id"],
                "category": "evidence" if str(case["task"]).startswith("Find") else "synthesis",
                "expectedSpecialist": (
                    "retrieval" if str(case["task"]).startswith("Find") else "synthesis"
                ),
                "errorCost": 2,
            }
            for case in cases
        ],
    }


class BlindRoutingAdjudicationTests(unittest.TestCase):
    def _write_json(self, directory: str, name: str, value: object) -> Path:
        path = Path(directory) / name
        path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def _write_candidates(
        self, directory: str, cases: list[dict[str, object]]
    ) -> Path:
        path = Path(directory) / "candidates.jsonl"
        path.write_text(
            "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
            encoding="utf-8",
        )
        return path

    def test_agreement_builds_phase17_dataset_without_leaking_tasks_in_report(self) -> None:
        marker = "private-natural-task-marker"
        cases = [_candidate(index, marker if index == 1 else "") for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            candidates_path = self._write_candidates(directory, cases)
            candidate_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
            a_path = self._write_json(directory, "a.json", _annotation("reviewer-a", cases, candidate_sha256))
            b_path = self._write_json(directory, "b.json", _annotation("reviewer-b", cases, candidate_sha256))
            candidates = load_candidates(candidates_path)
            expected_ids = {case["id"] for case in candidates}
            primary = (
                load_annotations(a_path, expected_ids, candidate_sha256),
                load_annotations(b_path, expected_ids, candidate_sha256),
            )
            report = compare_annotations(
                candidates_path, candidates, (a_path, b_path), primary
            )
            dataset = build_consensus_dataset(candidates, primary, report)
            dataset_path = Path(directory) / "dataset.jsonl"
            dataset_path.write_text(
                "\n".join(json.dumps(case, ensure_ascii=False) for case in dataset) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(report["specialistAgreement"], 1.0)
            self.assertEqual(report["categoryAgreement"], 1.0)
            self.assertEqual(report["cohenKappa"], 1.0)
            self.assertNotIn(marker, json.dumps(report, ensure_ascii=False))
            self.assertEqual(len(load_dataset(dataset_path)), 20)

    def test_disagreement_requires_distinct_adjudicator_and_exact_conflict_ids(self) -> None:
        cases = [_candidate(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            candidates_path = self._write_candidates(directory, cases)
            candidate_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
            annotation_a = _annotation("reviewer-a", cases, candidate_sha256)
            annotation_b = _annotation("reviewer-b", cases, candidate_sha256)
            annotation_b["labels"][0]["expectedSpecialist"] = "synthesis"
            annotation_b["labels"][0]["errorCost"] = 4
            a_path = self._write_json(directory, "a.json", annotation_a)
            b_path = self._write_json(directory, "b.json", annotation_b)
            candidates = load_candidates(candidates_path)
            expected_ids = {case["id"] for case in candidates}
            primary = (
                load_annotations(a_path, expected_ids, candidate_sha256),
                load_annotations(b_path, expected_ids, candidate_sha256),
            )
            report = compare_annotations(
                candidates_path, candidates, (a_path, b_path), primary
            )

            with self.assertRaisesRegex(ValueError, "require.*adjudication"):
                build_consensus_dataset(candidates, primary, report)

            conflict_id = cases[0]["id"]
            adjudication_value = {
                "schemaVersion": 1,
                "kind": "secure-agent-workbench/blind-routing-annotations",
                "candidateSha256": candidate_sha256,
                "reviewerId": "reviewer-c",
                "labels": [
                    {
                        "id": conflict_id,
                        "category": "evidence",
                        "expectedSpecialist": "retrieval",
                        "errorCost": 3,
                    }
                ],
            }
            adjudication_path = self._write_json(
                directory, "adjudication.json", adjudication_value
            )
            adjudication = load_annotations(
                adjudication_path, {conflict_id}, candidate_sha256
            )
            adjudication["labels"][conflict_id]["category"] = "other"
            with self.assertRaisesRegex(ValueError, "cannot change fields agreed"):
                build_consensus_dataset(candidates, primary, report, adjudication)

            adjudication["labels"][conflict_id]["category"] = "evidence"
            dataset = build_consensus_dataset(
                candidates, primary, report, adjudication
            )
            self.assertEqual(dataset[0]["expectedSpecialist"], "retrieval")
            self.assertEqual(dataset[0]["errorCost"], 3)

            adjudication["reviewerId"] = "reviewer-a"
            with self.assertRaisesRegex(ValueError, "must be distinct"):
                build_consensus_dataset(candidates, primary, report, adjudication)

    def test_rejects_same_primary_reviewer(self) -> None:
        cases = [_candidate(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            candidates_path = self._write_candidates(directory, cases)
            candidate_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
            a_path = self._write_json(directory, "a.json", _annotation("reviewer-a", cases, candidate_sha256))
            b_path = self._write_json(directory, "b.json", _annotation("reviewer-a", cases, candidate_sha256))
            candidates = load_candidates(candidates_path)
            expected_ids = {case["id"] for case in candidates}
            primary = (
                load_annotations(a_path, expected_ids, candidate_sha256),
                load_annotations(b_path, expected_ids, candidate_sha256),
            )
            with self.assertRaisesRegex(ValueError, "distinct reviewer"):
                compare_annotations(
                    candidates_path, candidates, (a_path, b_path), primary
                )

    def test_annotation_ids_must_exactly_match_candidates(self) -> None:
        cases = [_candidate(index) for index in range(1, 21)]
        with tempfile.TemporaryDirectory() as directory:
            candidates_path = self._write_candidates(directory, cases)
            candidate_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
            annotation = _annotation("reviewer-a", cases, candidate_sha256)
            annotation["labels"].pop()
            path = self._write_json(directory, "a.json", annotation)
            with self.assertRaisesRegex(ValueError, "exactly match"):
                load_annotations(
                    path, {case["id"] for case in cases}, candidate_sha256
                )

            annotation["labels"].append(annotation["labels"][-1])
            annotation["candidateSha256"] = "0" * 64
            path = self._write_json(directory, "wrong-hash.json", annotation)
            with self.assertRaisesRegex(ValueError, "candidate hash"):
                load_annotations(
                    path, {case["id"] for case in cases}, candidate_sha256
                )

    def test_cli_rejects_files_outside_private_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "private directory"):
                _require_private_path(Path(directory) / "candidate.jsonl")

    def test_cli_builds_private_dataset_without_printing_task_text(self) -> None:
        marker = "private-cli-task-marker"
        cases = [_candidate(index, marker if index == 1 else "") for index in range(1, 21)]
        private_root = Path("benchmarks/private")
        private_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=private_root) as directory:
            candidates = self._write_candidates(directory, cases)
            candidate_sha256 = hashlib.sha256(candidates.read_bytes()).hexdigest()
            annotation_a = self._write_json(
                directory, "a.json", _annotation("reviewer-a", cases, candidate_sha256)
            )
            annotation_b = self._write_json(
                directory, "b.json", _annotation("reviewer-b", cases, candidate_sha256)
            )
            dataset = Path(directory) / "dataset.jsonl"
            report = Path(directory) / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/blind_routing_adjudicate.py",
                    "--candidates",
                    str(candidates),
                    "--annotation-a",
                    str(annotation_a),
                    "--annotation-b",
                    str(annotation_b),
                    "--dataset",
                    str(dataset),
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn(marker, completed.stdout)
            self.assertNotIn(marker, report.read_text(encoding="utf-8"))
            self.assertEqual(len(load_dataset(dataset)), 20)


if __name__ == "__main__":
    unittest.main()
