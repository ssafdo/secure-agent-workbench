from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from agent_workbench.embeddings import Model2VecEmbeddingProvider
from agent_workbench.relevance import (
    AnswerabilityVerifier,
    OnnxQaAnswerabilityVerifier,
    OnnxRelevanceVerifier,
    RelevanceVerifier,
)
from agent_workbench.retrieval import search_documents


def _citation_is_correct(match: dict[str, Any], documents: dict[str, str]) -> bool:
    path = match.get("path")
    start = match.get("startLine")
    end = match.get("endLine")
    text = match.get("text")
    if not isinstance(path, str) or path not in documents:
        return False
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return False
    lines = documents[path].splitlines()
    return end <= len(lines) and "\n".join(lines[start - 1 : end]).strip() == text


def _wilson_interval(successes: int, total: int) -> dict[str, float]:
    if total == 0:
        return {"low": 0.0, "high": 1.0}
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + (z * z / total)
    center = (rate + (z * z / (2 * total))) / denominator
    margin = (
        z
        * math.sqrt((rate * (1 - rate) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return {"low": round(max(0.0, center - margin), 6), "high": round(min(1.0, center + margin), 6)}


def _dataset_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Retrieval dataset must contain at least one case.")
    shared = payload.get("documents")
    if shared is not None:
        if not isinstance(shared, list) or not shared:
            raise ValueError("Shared retrieval documents must be a non-empty list.")
        for case in cases:
            if "documents" in case:
                raise ValueError("A shared-corpus case cannot override documents.")
            case["documents"] = shared
    return cases


def _slice_metrics(case_results: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        grouped[str(result.get(field, "unspecified"))].append(result)
    slices: dict[str, dict[str, Any]] = {}
    for name, items in sorted(grouped.items()):
        passed = sum(bool(item["passed"]) for item in items)
        slices[name] = {
            "cases": len(items),
            "passed": passed,
            "passRate": round(passed / len(items), 6),
            "passRate95CI": _wilson_interval(passed, len(items)),
        }
    return slices


def _coverage_candidate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    rule: dict[str, Any],
) -> dict[str, Any]:
    multi_gain = (
        candidate["categorySlices"]["multi-evidence"]["passed"]
        - baseline["categorySlices"]["multi-evidence"]["passed"]
    )
    single_loss = (
        baseline["categorySlices"]["single-evidence"]["passed"]
        - candidate["categorySlices"]["single-evidence"]["passed"]
    )
    total_gain = candidate["passed"] - baseline["passed"]
    unsupported_non_decrease = (
        candidate["unsupportedAccuracy"] >= baseline["unsupportedAccuracy"]
    )
    checks = {
        "multiEvidenceGain": {
            "actual": multi_gain,
            "requiredAtLeast": rule["multiEvidencePassedGainAtLeast"],
            "passed": multi_gain >= rule["multiEvidencePassedGainAtLeast"],
        },
        "unsupportedNonDecrease": {
            "baseline": baseline["unsupportedAccuracy"],
            "candidate": candidate["unsupportedAccuracy"],
            "passed": unsupported_non_decrease,
        },
        "singleEvidenceLoss": {
            "actual": single_loss,
            "allowedAtMost": rule["singleEvidencePassedLossAtMost"],
            "passed": single_loss <= rule["singleEvidencePassedLossAtMost"],
        },
        "totalPassedGain": {
            "actual": total_gain,
            "requiredAtLeast": rule["totalPassedGainAtLeast"],
            "passed": total_gain >= rule["totalPassedGainAtLeast"],
        },
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def _answerability_candidate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    rule: dict[str, Any],
) -> dict[str, Any]:
    baseline_cases = {item["id"]: item for item in baseline["caseResults"]}
    candidate_cases = {item["id"]: item for item in candidate["caseResults"]}
    if baseline_cases.keys() != candidate_cases.keys():
        raise ValueError("Answerability candidates must evaluate identical cases.")

    def passed_count(results: dict[str, dict[str, Any]], predicate) -> int:
        return sum(
            bool(item["passed"])
            for item in results.values()
            if predicate(item)
        )

    unsupported = lambda item: not item["supported"]
    supported = lambda item: item["supported"]
    negative = lambda item: item["answerType"] == "negative"
    unsupported_gain = passed_count(candidate_cases, unsupported) - passed_count(
        baseline_cases, unsupported
    )
    supported_loss = passed_count(baseline_cases, supported) - passed_count(
        candidate_cases, supported
    )
    negative_loss = passed_count(baseline_cases, negative) - passed_count(
        candidate_cases, negative
    )
    total_gain = candidate["passed"] - baseline["passed"]
    checks = {
        "unsupportedPassedGain": {
            "actual": unsupported_gain,
            "requiredAtLeast": rule["unsupportedPassedGainAtLeast"],
            "passed": unsupported_gain >= rule["unsupportedPassedGainAtLeast"],
        },
        "supportedPassedLoss": {
            "actual": supported_loss,
            "allowedAtMost": rule["supportedPassedLossAtMost"],
            "passed": supported_loss <= rule["supportedPassedLossAtMost"],
        },
        "negativeAnswerPassedLoss": {
            "actual": negative_loss,
            "allowedAtMost": rule["negativeAnswerPassedLossAtMost"],
            "passed": negative_loss <= rule["negativeAnswerPassedLossAtMost"],
        },
        "totalPassedGain": {
            "actual": total_gain,
            "requiredAtLeast": rule["totalPassedGainAtLeast"],
            "passed": total_gain >= rule["totalPassedGainAtLeast"],
        },
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def evaluate(
    dataset: Path,
    provider: Model2VecEmbeddingProvider | None,
    *,
    minimum_hybrid_score: float | None = None,
    relevance_verifier: RelevanceVerifier | None = None,
    relevance_threshold: float = 0.5,
    decompose_verification_query: bool = False,
    atomic_relevance_threshold: float | None = None,
    require_complete_query_coverage: bool = False,
    answerability_verifier: AnswerabilityVerifier | None = None,
    answerability_threshold: float = 0.5,
    answerability_scope: str = "passage",
) -> dict[str, Any]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    cases = _dataset_cases(payload)
    reciprocal_ranks: list[float] = []
    recall_at_1: list[float] = []
    recall_at_3: list[float] = []
    citation_checks: list[bool] = []
    unsupported_checks: list[bool] = []
    case_results: list[dict[str, Any]] = []
    for case in cases:
        documents = {item["path"]: item["content"] for item in case["documents"]}
        result = search_documents(
            case["query"],
            list(documents.items()),
            limit=5,
            embedding_provider=provider,
            minimum_hybrid_score=minimum_hybrid_score,
            relevance_verifier=relevance_verifier,
            relevance_threshold=relevance_threshold,
            decompose_verification_query=decompose_verification_query,
            atomic_relevance_threshold=atomic_relevance_threshold,
            require_complete_query_coverage=require_complete_query_coverage,
            answerability_verifier=answerability_verifier,
            answerability_threshold=answerability_threshold,
            answerability_scope=answerability_scope,
        )
        matches = result["matches"]
        chunk_paths = [match["path"] for match in matches]
        paths = list(dict.fromkeys(chunk_paths))
        relevant = set(case["relevantPaths"])
        if case["supported"]:
            ranks = [index + 1 for index, path in enumerate(paths) if path in relevant]
            first_rank = min(ranks, default=0)
            reciprocal_ranks.append(0.0 if first_rank == 0 else 1.0 / first_rank)
            recall_at_1.append(len(relevant.intersection(paths[:1])) / len(relevant))
            recall_at_3.append(len(relevant.intersection(paths[:3])) / len(relevant))
            passed = relevant.issubset(paths[:3])
            failure_type = None if passed else "required-documents-not-covered-in-top-3"
        else:
            first_rank = 0
            passed = not matches
            unsupported_checks.append(passed)
            failure_type = None if passed else "unsupported-query-returned-evidence"
        citation_checks.extend(
            _citation_is_correct(match, documents) for match in matches
        )
        top_match = matches[0] if matches else {}
        second_score = matches[1]["score"] if len(matches) > 1 else None
        score_margin = (
            None
            if not matches
            else top_match["score"] - (second_score if second_score is not None else 0.0)
        )
        case_results.append(
            {
                "id": case["id"],
                "mode": result["retrievalMode"],
                "paths": paths,
                "chunkPaths": chunk_paths,
                "firstRelevantRank": first_rank,
                "language": case.get("language", "unspecified"),
                "category": case.get("category", "unspecified"),
                "answerType": case.get(
                    "answerType", "unanswerable" if not case["supported"] else "unspecified"
                ),
                "supported": bool(case["supported"]),
                "passed": passed,
                "failureType": failure_type,
                "topScore": top_match.get("score"),
                "topLexicalScore": top_match.get("lexicalScore"),
                "topSemanticScore": top_match.get("semanticScore"),
                "scoreMargin": None if score_margin is None else round(score_margin, 6),
                "verificationMode": result["verificationMode"],
                "verificationFailureReason": result["verificationFailureReason"],
                "answerabilityMode": result["answerabilityMode"],
                "topAnswerabilityScore": top_match.get("answerabilityScore"),
                "answerabilityScope": result["answerabilityScope"],
                "answerabilityCoverageComplete": result[
                    "answerabilityCoverageComplete"
                ],
                "answerabilitySetScores": result["answerabilitySetScores"],
                "verificationQueryVariantCount": len(
                    result["verificationQueryVariants"]
                ),
                "matchedQueryVariants": list(
                    dict.fromkeys(
                        match["matchedQueryVariant"]
                        for match in matches
                        if match["matchedQueryVariant"] is not None
                    )
                ),
                "queryCoverageRequired": result["queryCoverageRequired"],
                "queryCoverageComplete": result["queryCoverageComplete"],
                "coveredQueryVariants": result["coveredQueryVariants"],
            }
        )

    mean = lambda values: sum(values) / len(values) if values else 1.0
    supported_ids = {case["id"] for case in cases if case["supported"]}
    supported_results = [item for item in case_results if item["id"] in supported_ids]
    top_1_hits = sum(item["firstRelevantRank"] == 1 for item in supported_results)
    top_3_hits = sum(bool(item["passed"]) for item in supported_results)
    passed = sum(bool(item["passed"]) for item in case_results)
    return {
        "mode": (
            "decomposed-verified-hybrid"
            if provider is not None
            and relevance_verifier is not None
            and decompose_verification_query
            and answerability_verifier is None
            else "qa-set-answerability-verified-hybrid"
            if provider is not None
            and relevance_verifier is not None
            and answerability_verifier is not None
            and answerability_scope == "set"
            else "qa-answerability-verified-hybrid"
            if provider is not None
            and relevance_verifier is not None
            and answerability_verifier is not None
            else
            "verified-hybrid"
            if provider is not None and relevance_verifier is not None
            else "hybrid"
            if provider is not None
            else "verified-lexical"
            if relevance_verifier is not None
            else "lexical"
        ),
        "cases": len(cases),
        "supportedCases": len(supported_results),
        "recallAt1": round(mean(recall_at_1), 6),
        "recallAt3": round(mean(recall_at_3), 6),
        "top1HitRate": round(top_1_hits / len(supported_results), 6),
        "top1HitRate95CI": _wilson_interval(top_1_hits, len(supported_results)),
        "allRelevantInTop3Rate": round(top_3_hits / len(supported_results), 6),
        "allRelevantInTop3Rate95CI": _wilson_interval(top_3_hits, len(supported_results)),
        "mrr": round(mean(reciprocal_ranks), 6),
        "citationCorrectness": round(mean([float(v) for v in citation_checks]), 6),
        "unsupportedAccuracy": round(mean([float(v) for v in unsupported_checks]), 6),
        "passed": passed,
        "passRate": round(passed / len(case_results), 6),
        "passRate95CI": _wilson_interval(passed, len(case_results)),
        "languageSlices": _slice_metrics(case_results, "language"),
        "categorySlices": _slice_metrics(case_results, "category"),
        "failures": [item for item in case_results if not item["passed"]],
        "caseResults": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark lexical and hybrid retrieval.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/retrieval_cases.json"),
    )
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-improvement", action="store_true")
    parser.add_argument("--minimum-cases", type=int, default=1)
    parser.add_argument("--minimum-hybrid-score", type=float)
    parser.add_argument("--relevance-model-path", type=Path)
    parser.add_argument("--relevance-threshold", type=float, default=0.5)
    parser.add_argument("--decompose-verification-query", action="store_true")
    parser.add_argument("--atomic-relevance-threshold", type=float)
    parser.add_argument("--require-complete-query-coverage", action="store_true")
    parser.add_argument("--answerability-model-path", type=Path)
    parser.add_argument("--answerability-threshold", type=float, default=0.5)
    parser.add_argument(
        "--answerability-scope",
        choices=("passage", "set"),
        default="passage",
    )
    args = parser.parse_args()
    if (
        args.answerability_model_path is not None
        and args.relevance_model_path is None
    ):
        parser.error(
            "--answerability-model-path requires --relevance-model-path."
        )
    lexical = evaluate(args.dataset, None)
    if lexical["cases"] < args.minimum_cases:
        parser.error(
            f"Dataset has {lexical['cases']} cases; at least {args.minimum_cases} are required."
        )
    results: dict[str, Any] = {
        "schemaVersion": 1,
        "dataset": {
            "path": str(args.dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        },
        "lexical": lexical,
    }
    if args.model_path is not None:
        provider = Model2VecEmbeddingProvider.from_local_path(args.model_path)
        hybrid = evaluate(
            args.dataset,
            provider,
            minimum_hybrid_score=args.minimum_hybrid_score,
        )
        results["model"] = {
            "repository": provider.spec.repository,
            "revision": provider.spec.revision,
            "license": provider.spec.license,
            "fileSha256": provider.spec.file_sha256,
        }
        results["hybrid"] = hybrid
        if args.relevance_model_path is not None:
            verifier = OnnxRelevanceVerifier.from_local_path(
                args.relevance_model_path
            )
            verified = evaluate(
                args.dataset,
                provider,
                minimum_hybrid_score=args.minimum_hybrid_score,
                relevance_verifier=verifier,
                relevance_threshold=args.relevance_threshold,
            )
            results["relevanceModel"] = {
                "repository": verifier.spec.repository,
                "revision": verifier.spec.revision,
                "license": verifier.spec.license,
                "fileSha256": verifier.spec.file_sha256,
                "threshold": args.relevance_threshold,
            }
            results["verifiedHybrid"] = verified
            if args.decompose_verification_query:
                decomposed = evaluate(
                    args.dataset,
                    provider,
                    minimum_hybrid_score=args.minimum_hybrid_score,
                    relevance_verifier=verifier,
                    relevance_threshold=args.relevance_threshold,
                    decompose_verification_query=True,
                    atomic_relevance_threshold=args.atomic_relevance_threshold,
                    require_complete_query_coverage=(
                        args.require_complete_query_coverage
                    ),
                )
                results["decomposedVerifiedHybrid"] = decomposed
                results["relevanceModel"]["atomicThreshold"] = (
                    args.atomic_relevance_threshold
                )
                results["relevanceModel"]["completeCoverageRequired"] = (
                    args.require_complete_query_coverage
                )
                gate_rule = json.loads(
                    args.dataset.read_text(encoding="utf-8")
                ).get("selectionGate")
                if isinstance(gate_rule, dict):
                    results["candidateGate"] = _coverage_candidate_gate(
                        verified,
                        decomposed,
                        gate_rule,
                    )
            if args.answerability_model_path is not None:
                qa_verifier = OnnxQaAnswerabilityVerifier.from_local_path(
                    args.answerability_model_path
                )
                qa_candidate = evaluate(
                    args.dataset,
                    provider,
                    minimum_hybrid_score=args.minimum_hybrid_score,
                    relevance_verifier=verifier,
                    relevance_threshold=args.relevance_threshold,
                    decompose_verification_query=args.decompose_verification_query,
                    atomic_relevance_threshold=args.atomic_relevance_threshold,
                    require_complete_query_coverage=(
                        args.require_complete_query_coverage
                    ),
                    answerability_verifier=qa_verifier,
                    answerability_threshold=args.answerability_threshold,
                    answerability_scope=args.answerability_scope,
                )
                results["qaAnswerabilityModel"] = {
                    "repository": qa_verifier.spec.repository,
                    "revision": qa_verifier.spec.revision,
                    "license": qa_verifier.spec.license,
                    "fileSha256": qa_verifier.spec.file_sha256,
                    "threshold": args.answerability_threshold,
                    "scope": args.answerability_scope,
                }
                results["qaAnswerabilityVerifiedHybrid"] = qa_candidate
                answerability_gate = json.loads(
                    args.dataset.read_text(encoding="utf-8")
                ).get("answerabilityGate")
                if isinstance(answerability_gate, dict):
                    baseline = (
                        results.get("decomposedVerifiedHybrid")
                        or results["verifiedHybrid"]
                    )
                    results["answerabilityCandidateGate"] = (
                        _answerability_candidate_gate(
                            baseline,
                            qa_candidate,
                            answerability_gate,
                        )
                    )
        if args.require_improvement and not (
            (
                results.get("decomposedVerifiedHybrid")
                or results.get("verifiedHybrid")
                or hybrid
            )["recallAt1"]
            > lexical["recallAt1"]
            and (
                results.get("decomposedVerifiedHybrid")
                or results.get("verifiedHybrid")
                or hybrid
            )["mrr"]
            > lexical["mrr"]
            and (
                results.get("decomposedVerifiedHybrid")
                or results.get("verifiedHybrid")
                or hybrid
            )["citationCorrectness"]
            == 1.0
            and (
                results.get("decomposedVerifiedHybrid")
                or results.get("verifiedHybrid")
                or hybrid
            )["unsupportedAccuracy"]
            == 1.0
        ):
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 1
    elif args.relevance_model_path is not None:
        parser.error("--relevance-model-path requires --model-path")
    elif args.answerability_model_path is not None:
        parser.error("--answerability-model-path requires --model-path")
    rendered = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
