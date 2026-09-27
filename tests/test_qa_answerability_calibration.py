from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DATASET = ROOT / "benchmarks" / "qa_answerability_dev_v1.json"
CALIBRATION_ARTIFACT = (
    ROOT / "artifacts" / "retrieval" / "qa-answerability-calibration-v1.json"
)
INTEGRATION_DATASET = ROOT / "benchmarks" / "retrieval_qa_coverage_dev_v1.json"
INTEGRATION_ARTIFACT = (
    ROOT / "artifacts" / "retrieval" / "qa-answerability-development-v1.json"
)
SET_DATASET = ROOT / "benchmarks" / "qa_evidence_set_dev_v1.json"
SET_ARTIFACT = (
    ROOT / "artifacts" / "retrieval" / "qa-evidence-set-calibration-v1.json"
)


class QaAnswerabilityCalibrationTests(unittest.TestCase):
    def test_calibration_dataset_is_balanced_and_pre_registered(self) -> None:
        payload = json.loads(CALIBRATION_DATASET.read_text(encoding="utf-8"))
        cases = payload["cases"]

        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case["id"] for case in cases}), 48)
        self.assertEqual(sum(case["answerable"] for case in cases), 24)
        self.assertEqual(sum(case["language"] == "en" for case in cases), 24)
        self.assertEqual(sum(case["language"] == "zh" for case in cases), 24)
        self.assertTrue(
            all(case["expectedAnswers"] for case in cases if case["answerable"])
        )
        self.assertTrue(
            all(case["expectedAnswers"] == [] for case in cases if not case["answerable"])
        )

    def test_calibration_artifact_records_passed_gate(self) -> None:
        artifact = json.loads(CALIBRATION_ARTIFACT.read_text(encoding="utf-8"))

        self.assertEqual(
            artifact["dataset"]["sha256"],
            hashlib.sha256(CALIBRATION_DATASET.read_bytes()).hexdigest(),
        )
        self.assertEqual(artifact["selected"]["threshold"], 0.901)
        self.assertTrue(artifact["candidateGate"]["passed"])
        self.assertEqual(artifact["selected"]["answerSpanAccuracy"], 1.0)

    def test_integration_artifact_records_failed_gate(self) -> None:
        artifact = json.loads(INTEGRATION_ARTIFACT.read_text(encoding="utf-8"))

        self.assertEqual(
            artifact["dataset"]["sha256"],
            hashlib.sha256(INTEGRATION_DATASET.read_bytes()).hexdigest(),
        )
        self.assertFalse(artifact["answerabilityCandidateGate"]["passed"])
        self.assertEqual(artifact["decomposedVerifiedHybrid"]["passed"], 24)
        self.assertEqual(artifact["qaAnswerabilityVerifiedHybrid"]["passed"], 19)

    def test_set_calibration_dataset_is_new_and_balanced(self) -> None:
        payload = json.loads(SET_DATASET.read_text(encoding="utf-8"))
        cases = payload["cases"]
        earlier = json.loads(CALIBRATION_DATASET.read_text(encoding="utf-8"))["cases"]

        self.assertEqual(len(cases), 40)
        self.assertEqual(sum(case["answerable"] for case in cases), 20)
        self.assertEqual(sum(case["language"] == "en" for case in cases), 20)
        self.assertEqual(sum(case["language"] == "zh" for case in cases), 20)
        self.assertTrue(all(len(case["passages"]) >= 2 for case in cases))
        self.assertFalse(
            {case["query"] for case in cases}.intersection(
                case["query"] for case in earlier
            )
        )

    def test_set_calibration_artifact_records_failed_gate(self) -> None:
        artifact = json.loads(SET_ARTIFACT.read_text(encoding="utf-8"))

        self.assertEqual(
            artifact["dataset"]["sha256"],
            hashlib.sha256(SET_DATASET.read_bytes()).hexdigest(),
        )
        self.assertEqual(artifact["selected"]["threshold"], 0.859)
        self.assertFalse(artifact["candidateGate"]["passed"])
        self.assertFalse(
            artifact["candidateGate"]["checks"]["topicRelatedMissingRecall"][
                "passed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
