from __future__ import annotations

import unittest

from scripts.calibrate_relevance_verifier import _metrics, _select


class RelevanceCalibrationTests(unittest.TestCase):
    def test_metrics_report_both_class_recalls(self) -> None:
        cases = [
            {"relevant": True, "score": 0.9},
            {"relevant": True, "score": 0.4},
            {"relevant": False, "score": 0.6},
            {"relevant": False, "score": 0.1},
        ]

        result = _metrics(cases, 0.5)

        self.assertEqual(result["positiveRecall"], 0.5)
        self.assertEqual(result["negativeRecall"], 0.5)
        self.assertEqual(result["balancedAccuracy"], 0.5)

    def test_selection_obeys_recall_constraint_and_documented_ties(self) -> None:
        rows = [
            {"threshold": 0.4, "positiveRecall": 1.0, "negativeRecall": 0.8,
             "balancedAccuracy": 0.9, "worstClassRecall": 0.8},
            {"threshold": 0.5, "positiveRecall": 0.9, "negativeRecall": 0.9,
             "balancedAccuracy": 0.9, "worstClassRecall": 0.9},
            {"threshold": 0.6, "positiveRecall": 0.8, "negativeRecall": 1.0,
             "balancedAccuracy": 0.9, "worstClassRecall": 0.8},
        ]

        self.assertEqual(_select(rows)["threshold"], 0.5)


if __name__ == "__main__":
    unittest.main()
