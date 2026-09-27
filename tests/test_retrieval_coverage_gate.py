from __future__ import annotations

import unittest

from scripts.benchmark_retrieval import (
    _answerability_candidate_gate,
    _coverage_candidate_gate,
)


class RetrievalCoverageGateTests(unittest.TestCase):
    def test_gate_requires_every_pre_registered_condition(self) -> None:
        baseline = {
            "passed": 10,
            "unsupportedAccuracy": 1.0,
            "categorySlices": {
                "multi-evidence": {"passed": 1},
                "single-evidence": {"passed": 5},
            },
        }
        candidate = {
            "passed": 13,
            "unsupportedAccuracy": 0.9,
            "categorySlices": {
                "multi-evidence": {"passed": 5},
                "single-evidence": {"passed": 5},
            },
        }
        rule = {
            "multiEvidencePassedGainAtLeast": 4,
            "singleEvidencePassedLossAtMost": 1,
            "totalPassedGainAtLeast": 3,
        }

        result = _coverage_candidate_gate(baseline, candidate, rule)

        self.assertFalse(result["passed"])
        self.assertTrue(result["checks"]["multiEvidenceGain"]["passed"])
        self.assertFalse(result["checks"]["unsupportedNonDecrease"]["passed"])

    def test_gate_passes_when_all_conditions_hold(self) -> None:
        baseline = {
            "passed": 10,
            "unsupportedAccuracy": 0.8,
            "categorySlices": {
                "multi-evidence": {"passed": 1},
                "single-evidence": {"passed": 5},
            },
        }
        candidate = {
            "passed": 14,
            "unsupportedAccuracy": 0.8,
            "categorySlices": {
                "multi-evidence": {"passed": 5},
                "single-evidence": {"passed": 5},
            },
        }
        rule = {
            "multiEvidencePassedGainAtLeast": 4,
            "singleEvidencePassedLossAtMost": 1,
            "totalPassedGainAtLeast": 3,
        }

        self.assertTrue(_coverage_candidate_gate(baseline, candidate, rule)["passed"])

    def test_answerability_gate_counts_supported_and_negative_regressions(self) -> None:
        baseline = {
            "passed": 3,
            "caseResults": [
                {"id": "a", "supported": True, "answerType": "affirmative", "passed": True},
                {"id": "b", "supported": True, "answerType": "negative", "passed": True},
                {"id": "c", "supported": False, "answerType": "unanswerable", "passed": False},
                {"id": "d", "supported": False, "answerType": "unanswerable", "passed": True},
            ],
        }
        candidate = {
            "passed": 2,
            "caseResults": [
                {"id": "a", "supported": True, "answerType": "affirmative", "passed": True},
                {"id": "b", "supported": True, "answerType": "negative", "passed": False},
                {"id": "c", "supported": False, "answerType": "unanswerable", "passed": True},
                {"id": "d", "supported": False, "answerType": "unanswerable", "passed": False},
            ],
        }
        rule = {
            "unsupportedPassedGainAtLeast": 1,
            "supportedPassedLossAtMost": 1,
            "negativeAnswerPassedLossAtMost": 0,
            "totalPassedGainAtLeast": 1,
        }

        result = _answerability_candidate_gate(baseline, candidate, rule)

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["negativeAnswerPassedLoss"]["passed"])
        self.assertFalse(result["checks"]["totalPassedGain"]["passed"])


if __name__ == "__main__":
    unittest.main()
