from __future__ import annotations

import unittest
from pathlib import Path

from scripts.benchmark_supervisor_routing import evaluate


class SupervisorNaturalisticDevelopmentBenchmarkTests(unittest.TestCase):
    def test_bilingual_naturalistic_development_set(self) -> None:
        result = evaluate(Path("benchmarks/supervisor_naturalistic_dev_cases.json"))

        self.assertEqual(result["cases"], 60)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["weightedError"], 0)
        self.assertEqual(result["languageSlices"]["en"]["cases"], 30)
        self.assertEqual(result["languageSlices"]["zh"]["cases"], 30)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
