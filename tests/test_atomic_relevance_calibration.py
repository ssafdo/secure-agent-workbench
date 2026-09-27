from __future__ import annotations

import unittest

from scripts.calibrate_atomic_relevance import _metrics


class AtomicRelevanceCalibrationTests(unittest.TestCase):
    def test_preserves_three_decimal_threshold(self) -> None:
        cases = [
            {"relevant": True, "score": 0.02},
            {"relevant": False, "score": 0.001},
        ]

        result = _metrics(cases, 0.015)

        self.assertEqual(result["threshold"], 0.015)
        self.assertEqual(result["positiveRecall"], 1.0)
        self.assertEqual(result["negativeRecall"], 1.0)


if __name__ == "__main__":
    unittest.main()
