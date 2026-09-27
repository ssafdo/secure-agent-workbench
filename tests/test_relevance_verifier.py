from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

import numpy

from agent_workbench.relevance import (
    OnnxAnswerabilityVerifier,
    OnnxQaAnswerabilityVerifier,
    OnnxRelevanceVerifier,
    decompose_query,
)
from agent_workbench.retrieval import search_documents


class RelevanceVerifierTests(unittest.TestCase):
    class FixedVerifier:
        name = "fixed-relevance-verifier"

        def __init__(self, scores):
            self.scores = scores

        def score(self, query, passages):
            del query, passages
            return self.scores

    class FailingVerifier:
        name = "failing-relevance-verifier"

        def score(self, query, passages):
            del query, passages
            raise RuntimeError("simulated verifier failure")

    class FixedAnswerabilityVerifier:
        name = "fixed-answerability-verifier"

        def __init__(self, scores):
            self.scores = scores

        def score(self, query, passages):
            del query, passages
            return self.scores

    class QueryAwareVerifier:
        name = "query-aware-verifier"

        def score(self, query, passages):
            values = []
            for passage in passages:
                if "deployment approval" in query.lower():
                    values.append(0.9 if "owner approval" in passage.lower() else 0.1)
                elif "rollback policy" in query.lower():
                    values.append(0.9 if "error rate" in passage.lower() else 0.1)
                else:
                    values.append(0.2)
            return values

    def test_verifier_filters_candidates_below_threshold(self) -> None:
        result = search_documents(
            "container isolation",
            [
                ("inputs/a.md", "Container isolation uses a read-only root."),
                ("inputs/b.md", "Container isolation has an unrelated mention."),
            ],
            relevance_verifier=self.FixedVerifier([0.91, 0.2]),
            relevance_threshold=0.7,
        )

        self.assertEqual(result["verificationMode"], "verified")
        self.assertEqual(result["relevanceVerifier"], "fixed-relevance-verifier")
        self.assertEqual(result["relevanceThreshold"], 0.7)
        self.assertIsNone(result["verificationFailureReason"])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["relevanceScore"], 0.91)

    def test_verifier_failure_returns_no_evidence(self) -> None:
        result = search_documents(
            "container isolation",
            [("inputs/a.md", "Container isolation uses a read-only root.")],
            relevance_verifier=self.FailingVerifier(),
        )

        self.assertEqual(result["verificationMode"], "failed-closed")
        self.assertEqual(
            result["verificationFailureReason"],
            "relevance verification failed: RuntimeError",
        )
        self.assertEqual(result["matches"], [])

    def test_invalid_verifier_scores_fail_closed(self) -> None:
        for scores in ([math.nan], [1.1], [True], []):
            with self.subTest(scores=scores):
                result = search_documents(
                    "container isolation",
                    [("inputs/a.md", "Container isolation uses a read-only root.")],
                    relevance_verifier=self.FixedVerifier(scores),
                )

                self.assertEqual(result["verificationMode"], "failed-closed")
                self.assertEqual(result["matches"], [])
                self.assertEqual(
                    result["verificationFailureReason"],
                    "relevance verification failed: ValueError",
                )

    def test_relevance_threshold_must_be_finite_probability(self) -> None:
        for threshold in (-0.1, 1.1, math.inf, math.nan):
            with self.subTest(threshold=threshold):
                with self.assertRaisesRegex(ValueError, "relevance_threshold"):
                    search_documents(
                        "query",
                        [("inputs/a.md", "query")],
                        relevance_threshold=threshold,
                    )

    def test_atomic_relevance_threshold_must_be_finite_probability(self) -> None:
        for threshold in (-0.1, 1.1, math.inf, math.nan):
            with self.subTest(threshold=threshold):
                with self.assertRaisesRegex(ValueError, "atomic_relevance_threshold"):
                    search_documents(
                        "Compare a and b.",
                        [("inputs/a.md", "a")],
                        atomic_relevance_threshold=threshold,
                    )

    def test_complete_coverage_requires_decomposition(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires"):
            search_documents(
                "query",
                [("inputs/a.md", "query")],
                require_complete_query_coverage=True,
            )

    def test_answerability_verifier_requires_relevance_verifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires relevance_verifier"):
            search_documents(
                "query",
                [("inputs/a.md", "query")],
                answerability_verifier=self.FixedAnswerabilityVerifier([0.9]),
            )

    def test_answerability_threshold_must_be_finite_probability(self) -> None:
        for threshold in (-0.1, 1.1, math.inf, math.nan):
            with self.subTest(threshold=threshold):
                with self.assertRaisesRegex(ValueError, "answerability_threshold"):
                    search_documents(
                        "query",
                        [("inputs/a.md", "query")],
                        answerability_threshold=threshold,
                    )

    def test_answerability_scope_must_be_supported(self) -> None:
        with self.assertRaisesRegex(ValueError, "answerability_scope"):
            search_documents(
                "query",
                [("inputs/a.md", "query")],
                answerability_scope="document",
            )

    def test_missing_local_model_is_rejected(self) -> None:
        with self.assertRaises(FileNotFoundError):
            OnnxRelevanceVerifier.from_local_path("missing/relevance/model")

    def test_incomplete_local_model_is_rejected_before_loading_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum|missing"):
                OnnxRelevanceVerifier.from_local_path(directory)

    def test_missing_local_answerability_model_is_rejected(self) -> None:
        with self.assertRaises(FileNotFoundError):
            OnnxAnswerabilityVerifier.from_local_path("missing/answerability/model")

    def test_answerability_score_counts_entailment_and_contradiction(self) -> None:
        class Encoding:
            ids = [0, 2]
            attention_mask = [1, 1]
            type_ids = [0, 0]

        class Tokenizer:
            def encode_batch(self, pairs):
                return [Encoding() for _ in pairs]

        class Input:
            name = "input_ids"

        class Session:
            def get_inputs(self):
                return [Input()]

            def run(self, outputs, inputs):
                del outputs, inputs
                return [numpy.asarray([[2.0, 0.0, 1.0], [0.0, 3.0, 0.0]])]

        verifier = OnnxAnswerabilityVerifier(Session(), Tokenizer())
        scores = verifier.score("Does the rule allow this?", ["No.", "Topic only."])

        self.assertGreater(scores[0], 0.8)
        self.assertLess(scores[1], 0.1)

    def test_qa_answerability_extracts_context_span_and_scores_margin(self) -> None:
        class Encoding:
            ids = [1, 2, 3, 4, 5]
            attention_mask = [1, 1, 1, 1, 1]
            type_ids = [0, 0, 0, 0, 0]
            sequence_ids = [None, 0, None, 1, None]
            offsets = [(0, 0), (0, 5), (0, 0), (9, 12), (0, 0)]

        class Tokenizer:
            def encode_batch(self, pairs):
                return [Encoding() for _ in pairs]

        class Input:
            name = "input_ids"

        class Session:
            def get_inputs(self):
                return [Input()]

            def run(self, outputs, inputs):
                del outputs, inputs
                return [
                    numpy.asarray([[0.0, -1.0, -1.0, 3.0, -1.0]]),
                    numpy.asarray([[0.0, -1.0, -1.0, 3.0, -1.0]]),
                ]

        verifier = OnnxQaAnswerabilityVerifier(Session(), Tokenizer())
        assessment = verifier.assess("Which code?", ["Use code ABC now."])[0]

        self.assertGreater(assessment.score, 0.99)
        self.assertEqual(assessment.answer, "ABC")
        self.assertEqual((assessment.start, assessment.end), (9, 12))

    def test_answerability_gate_rejects_topic_only_candidate(self) -> None:
        result = search_documents(
            "Which courier handles returns?",
            [
                ("inputs/answer.md", "Returns use Atlas Courier."),
                ("inputs/topic.md", "Returns require manager approval."),
            ],
            relevance_verifier=self.FixedVerifier([0.9, 0.9]),
            relevance_threshold=0.7,
            answerability_verifier=self.FixedAnswerabilityVerifier([0.9, 0.2]),
            answerability_threshold=0.6,
        )

        self.assertEqual(result["answerabilityMode"], "verified")
        self.assertEqual(result["answerabilityThreshold"], 0.6)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["path"], "inputs/answer.md")
        self.assertEqual(result["matches"][0]["answerabilityScore"], 0.9)

    def test_answerability_failure_returns_no_evidence(self) -> None:
        result = search_documents(
            "Which courier handles returns?",
            [("inputs/answer.md", "Returns use Atlas Courier.")],
            relevance_verifier=self.FixedVerifier([0.9]),
            answerability_verifier=self.FailingVerifier(),
        )

        self.assertEqual(result["verificationMode"], "failed-closed")
        self.assertEqual(result["answerabilityMode"], "failed-closed")
        self.assertEqual(result["matches"], [])
        self.assertEqual(
            result["verificationFailureReason"],
            "evidence verification failed: RuntimeError",
        )

    def test_set_answerability_keeps_all_selected_evidence(self) -> None:
        class SetVerifier:
            name = "set-verifier"

            def score(self, query, passages):
                self.assert_combined(passages)
                return [0.95]

            @staticmethod
            def assert_combined(passages):
                if len(passages) != 1 or "approval.md" not in passages[0] or "rollback.md" not in passages[0]:
                    raise AssertionError("Expected one combined evidence set.")

        result = search_documents(
            "Compare the controls for deployment approval and rollback policy.",
            [
                ("inputs/approval.md", "Owner approval is required before release."),
                ("inputs/rollback.md", "Rollback starts when the error rate is high."),
            ],
            relevance_verifier=self.QueryAwareVerifier(),
            relevance_threshold=0.7,
            atomic_relevance_threshold=0.5,
            decompose_verification_query=True,
            require_complete_query_coverage=True,
            answerability_verifier=SetVerifier(),
            answerability_threshold=0.9,
            answerability_scope="set",
        )

        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(result["answerabilityScope"], "set")
        self.assertTrue(result["answerabilityCoverageComplete"])
        self.assertEqual(len(result["answerabilitySetScores"]), 2)

    def test_set_answerability_rejects_incomplete_atomic_coverage(self) -> None:
        class PartialSetVerifier:
            name = "partial-set-verifier"

            def score(self, query, passages):
                del passages
                return [0.95 if "deployment approval" in query.lower() else 0.2]

        result = search_documents(
            "Compare the controls for deployment approval and rollback policy.",
            [
                ("inputs/approval.md", "Owner approval is required before release."),
                ("inputs/rollback.md", "Rollback starts when the error rate is high."),
            ],
            relevance_verifier=self.QueryAwareVerifier(),
            relevance_threshold=0.7,
            atomic_relevance_threshold=0.5,
            decompose_verification_query=True,
            require_complete_query_coverage=True,
            answerability_verifier=PartialSetVerifier(),
            answerability_threshold=0.9,
            answerability_scope="set",
        )

        self.assertEqual(result["matches"], [])
        self.assertFalse(result["answerabilityCoverageComplete"])
        self.assertEqual(len(result["answerabilitySetScores"]), 2)

    def test_decomposes_explicit_english_comparison(self) -> None:
        variants = decompose_query(
            "Compare the controls for deployment approval and rollback policy."
        )

        self.assertEqual(len(variants), 3)
        self.assertEqual(
            variants[1], "What are the controls for deployment approval?"
        )
        self.assertEqual(variants[2], "What are the controls for rollback policy?")

    def test_decomposes_explicit_chinese_respectively_query(self) -> None:
        variants = decompose_query("发布审批和回滚策略分别有什么要求？")

        self.assertEqual(len(variants), 3)
        self.assertIn("发布审批", variants[1])
        self.assertIn("回滚策略", variants[2])

    def test_does_not_split_ordinary_conjunction(self) -> None:
        self.assertEqual(
            decompose_query("May batteries and plastic bags enter the blue cart?"),
            ("May batteries and plastic bags enter the blue cart?",),
        )
        self.assertEqual(
            decompose_query("电池和塑料袋能放入回收桶吗？"),
            ("电池和塑料袋能放入回收桶吗？",),
        )

    def test_decomposed_verification_can_keep_distinct_evidence(self) -> None:
        result = search_documents(
            "Compare the controls for deployment approval and rollback policy.",
            [
                ("inputs/approval.md", "Owner approval is required before release."),
                ("inputs/rollback.md", "Rollback starts when the error rate is high."),
            ],
            relevance_verifier=self.QueryAwareVerifier(),
            relevance_threshold=0.7,
            decompose_verification_query=True,
        )

        self.assertEqual(result["verificationMode"], "decomposed-verified")
        self.assertEqual(len(result["verificationQueryVariants"]), 3)
        self.assertEqual(
            {match["path"] for match in result["matches"]},
            {"inputs/approval.md", "inputs/rollback.md"},
        )
        self.assertTrue(
            all(match["matchedQueryVariant"] for match in result["matches"])
        )

    def test_verifier_receives_path_context_without_changing_citation_text(self) -> None:
        class CapturingVerifier:
            name = "capturing-verifier"

            def __init__(self):
                self.passages = []

            def score(self, query, passages):
                del query
                self.passages = list(passages)
                return [0.9 for _ in passages]

        verifier = CapturingVerifier()
        result = search_documents(
            "welding",
            [("inputs/welding-safety.md", "Wear a rated helmet.")],
            relevance_verifier=verifier,
            relevance_threshold=0.7,
        )

        self.assertEqual(
            verifier.passages, ["inputs/welding-safety.md\nWear a rated helmet."]
        )
        self.assertEqual(result["matches"][0]["text"], "Wear a rated helmet.")

    def test_decomposed_aggregation_reserves_distinct_paths_per_atomic_query(self) -> None:
        class CoverageVerifier:
            name = "coverage-verifier"

            def score(self, query, passages):
                scores = []
                for passage in passages:
                    is_rollback = "rollback" in passage.lower()
                    is_primary = "approval-a" in passage.lower()
                    if "deployment approval" in query.lower():
                        scores.append(0.1 if is_rollback else 0.95 if is_primary else 0.9)
                    elif "rollback policy" in query.lower():
                        scores.append(0.85 if is_rollback else 0.1)
                    else:
                        scores.append(0.7 if is_rollback else 0.99 if is_primary else 0.8)
                return scores

        result = search_documents(
            "Compare the controls for deployment approval and rollback policy.",
            [
                ("inputs/approval-a.md", "Deployment approval needs an owner."),
                ("inputs/approval-b.md", "Deployment approval needs an operator."),
                ("inputs/rollback.md", "Rollback policy uses an error-rate trigger."),
            ],
            limit=2,
            relevance_verifier=CoverageVerifier(),
            relevance_threshold=0.7,
            decompose_verification_query=True,
        )

        self.assertEqual(
            {match["path"] for match in result["matches"]},
            {"inputs/approval-a.md", "inputs/rollback.md"},
        )

    def test_complete_coverage_refuses_partial_comparison_evidence(self) -> None:
        class PartialVerifier:
            name = "partial-verifier"

            def score(self, query, passages):
                if "deployment approval" in query.lower():
                    return [0.9 for _ in passages]
                return [0.1 for _ in passages]

        result = search_documents(
            "Compare the controls for deployment approval and rollback policy.",
            [("inputs/approval.md", "Deployment approval needs an owner.")],
            relevance_verifier=PartialVerifier(),
            relevance_threshold=0.7,
            atomic_relevance_threshold=0.5,
            decompose_verification_query=True,
            require_complete_query_coverage=True,
        )

        self.assertEqual(result["matches"], [])
        self.assertTrue(result["queryCoverageRequired"])
        self.assertFalse(result["queryCoverageComplete"])
        self.assertEqual(len(result["coveredQueryVariants"]), 1)


if __name__ == "__main__":
    unittest.main()
