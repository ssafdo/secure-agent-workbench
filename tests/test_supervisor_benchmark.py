from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.benchmark_supervisor import evaluate


class SupervisorBenchmarkTests(unittest.TestCase):
    def test_script_runs_from_repository_root_without_pythonpath(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "scripts/benchmark_supervisor.py", "--require-improvement"],
            cwd=Path(__file__).resolve().parent.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_supervisor_improves_mixed_workload_without_regressing_synthesis(self) -> None:
        result = evaluate(Path("benchmarks/supervisor_cases.json"))
        self.assertEqual(result["single"]["successRate"], 0.5)
        self.assertEqual(result["supervisor"]["successRate"], 1.0)
        self.assertEqual(result["successRateDelta"], 0.5)
        synthesis = [
            case
            for case in result["supervisor"]["caseResults"]
            if case["id"].startswith("synthesis-")
        ]
        self.assertTrue(all(case["passed"] for case in synthesis))
        self.assertTrue(all(case["routingCorrect"] for case in synthesis))


if __name__ == "__main__":
    unittest.main()
