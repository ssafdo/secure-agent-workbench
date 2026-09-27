from __future__ import annotations

import unittest
from pathlib import Path

from agent_workbench.embeddings import Model2VecEmbeddingProvider
from scripts.benchmark_retrieval import evaluate


DATASET = Path("benchmarks/retrieval_challenge_v1.json")
MODEL = Path("runtime/models/potion-multilingual-128M-i8")


class RetrievalChallengeBenchmarkTests(unittest.TestCase):
    def test_shared_corpus_challenge_reports_failures_and_slices(self) -> None:
        result = evaluate(DATASET, None)

        self.assertEqual(result["cases"], 40)
        self.assertEqual(result["supportedCases"], 30)
        self.assertEqual(result["languageSlices"]["en"]["cases"], 20)
        self.assertEqual(result["languageSlices"]["zh"]["cases"], 20)
        self.assertEqual(result["categorySlices"]["unsupported"]["cases"], 10)
        self.assertGreater(len(result["failures"]), 0)
        self.assertLess(result["passRate95CI"]["low"], result["passRate95CI"]["high"])

    @unittest.skipUnless(MODEL.is_dir(), "Pinned local embedding model is not installed")
    def test_hybrid_improves_top_three_recall_and_reports_remaining_failures(self) -> None:
        lexical = evaluate(DATASET, None)
        hybrid = evaluate(DATASET, Model2VecEmbeddingProvider.from_local_path(MODEL))

        self.assertGreater(hybrid["recallAt3"], lexical["recallAt3"])
        self.assertGreater(hybrid["mrr"], lexical["mrr"])
        self.assertGreater(len(hybrid["failures"]), 0)


if __name__ == "__main__":
    unittest.main()
