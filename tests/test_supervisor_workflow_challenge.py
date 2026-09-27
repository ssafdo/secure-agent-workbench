from __future__ import annotations

import os
import unittest
from pathlib import Path

from scripts.benchmark_supervisor import evaluate


DATASET = Path("benchmarks/supervisor_workflow_challenge_v1.json")
MODEL = Path("runtime/models/potion-multilingual-128M-i8")


class SupervisorWorkflowChallengeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_model_path = os.environ.get(
            "AGENT_WORKBENCH_EMBEDDING_MODEL_PATH"
        )
        if MODEL.is_dir():
            os.environ["AGENT_WORKBENCH_EMBEDDING_MODEL_PATH"] = str(MODEL)

    def tearDown(self) -> None:
        if self.previous_model_path is None:
            os.environ.pop("AGENT_WORKBENCH_EMBEDDING_MODEL_PATH", None)
        else:
            os.environ[
                "AGENT_WORKBENCH_EMBEDDING_MODEL_PATH"
            ] = self.previous_model_path

    def test_larger_workflow_set_improves_without_requiring_a_perfect_score(self) -> None:
        result = evaluate(DATASET)

        self.assertEqual(result["single"]["cases"], 24)
        self.assertEqual(result["supervisor"]["cases"], 24)
        self.assertGreater(
            result["supervisor"]["successRate"], result["single"]["successRate"]
        )
        self.assertLess(
            result["supervisor"]["averageToolCalls"],
            result["single"]["averageToolCalls"],
        )
        self.assertGreater(len(result["supervisor"]["failures"]), 0)
        self.assertEqual(result["supervisor"]["languageSlices"]["en"]["cases"], 12)
        self.assertEqual(result["supervisor"]["languageSlices"]["zh"]["cases"], 12)


if __name__ == "__main__":
    unittest.main()
