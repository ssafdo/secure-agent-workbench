from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "answerability_dev_v1.json"
ARTIFACT = ROOT / "artifacts" / "retrieval" / "answerability-calibration-v1.json"


class AnswerabilityCalibrationTests(unittest.TestCase):
    def test_dataset_is_balanced_and_pre_registered(self) -> None:
        payload = json.loads(DATASET.read_text(encoding="utf-8"))
        cases = payload["cases"]

        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case["id"] for case in cases}), 48)
        self.assertEqual(sum(case["answerable"] for case in cases), 24)
        self.assertEqual(sum(case["language"] == "en" for case in cases), 24)
        self.assertEqual(sum(case["language"] == "zh" for case in cases), 24)
        self.assertEqual(
            payload["selectionRule"]["thresholdGrid"],
            {"start": 0.001, "stop": 0.999, "step": 0.001},
        )
        self.assertEqual(
            payload["candidateGate"]["topicRelatedMissingRecallAtLeast"],
            0.75,
        )

    def test_artifact_is_bound_to_dataset_and_records_failed_gate(self) -> None:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))

        self.assertEqual(
            artifact["dataset"]["sha256"], hashlib.sha256(DATASET.read_bytes()).hexdigest()
        )
        self.assertEqual(artifact["dataset"]["split"], "calibration-only")
        self.assertEqual(artifact["selected"]["threshold"], 0.197)
        self.assertFalse(artifact["candidateGate"]["passed"])
        self.assertFalse(
            artifact["candidateGate"]["checks"]["worstClassRecall"]["passed"]
        )


if __name__ == "__main__":
    unittest.main()
