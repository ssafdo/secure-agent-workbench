from __future__ import annotations

import unittest
from pathlib import Path

from agent_workbench.embeddings import (
    E5_MODEL_SPEC,
    POTION_MODEL_SPEC,
    Model2VecEmbeddingProvider,
)
from agent_workbench.retrieval import search_documents


class RetrievalCalibrationTests(unittest.TestCase):
    def test_final_hybrid_score_floor_filters_a_low_confidence_match(self) -> None:
        class FixedProvider:
            name = "fixed"

            def encode(self, texts):
                return [[1.0, 0.0], [0.3, 0.953939]]

        result = search_documents(
            "unrelated query",
            [("inputs/source.md", "different material")],
            embedding_provider=FixedProvider(),
            minimum_hybrid_score=0.2,
        )

        self.assertEqual(result["matches"], [])
        self.assertEqual(result["minimumHybridScore"], 0.2)

    def test_only_checksum_approved_models_can_load(self) -> None:
        potion = Path("runtime/models/potion-multilingual-128M-i8")
        e5 = Path("runtime/models/multilingual-e5-small-distilled-16m")
        if potion.is_dir():
            self.assertEqual(
                Model2VecEmbeddingProvider.from_local_path(potion).spec,
                POTION_MODEL_SPEC,
            )
        if e5.is_dir():
            self.assertEqual(
                Model2VecEmbeddingProvider.from_local_path(e5).spec,
                E5_MODEL_SPEC,
            )


if __name__ == "__main__":
    unittest.main()
