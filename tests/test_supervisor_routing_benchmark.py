from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark_supervisor_routing import evaluate


class SupervisorRoutingBenchmarkTests(unittest.TestCase):
    def test_fixed_bilingual_dataset_has_auditable_slices(self) -> None:
        result = evaluate(Path("benchmarks/supervisor_routing_cases.json"))

        self.assertEqual(result["cases"], 50)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["weightedError"], 0)
        self.assertEqual(result["languageSlices"]["en"]["cases"], 25)
        self.assertEqual(result["languageSlices"]["zh"]["cases"], 25)
        self.assertEqual(result["conflictCorrect"], result["conflictCases"])
        self.assertEqual(result["defaultCases"], 4)
        self.assertEqual(result["lowConfidenceDefaults"], 0)
        self.assertEqual(result["errors"], [])

    def test_rejects_duplicate_or_undersized_dataset(self) -> None:
        invalid = {
            "schemaVersion": 1,
            "cases": [
                {
                    "id": "duplicate",
                    "language": "en",
                    "category": "evidence",
                    "task": "Find evidence.",
                    "expectedSpecialist": "retrieval",
                    "errorCost": 1,
                }
            ]
            * 50,
        }
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "invalid.json"
            dataset.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                evaluate(dataset)


if __name__ == "__main__":
    unittest.main()
