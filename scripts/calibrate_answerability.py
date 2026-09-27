from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_workbench.relevance import OnnxAnswerabilityVerifier


def _rate(value: int, total: int) -> float:
    return value / total if total else 0.0


def _metrics(cases: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    positives = [case for case in cases if case["answerable"]]
    negatives = [case for case in cases if not case["answerable"]]
    true_positive = sum(case["score"] >= threshold for case in positives)
    true_negative = sum(case["score"] < threshold for case in negatives)
    positive_recall = _rate(true_positive, len(positives))
    negative_recall = _rate(true_negative, len(negatives))
    return {
        "threshold": round(threshold, 3),
        "answerableRecall": round(positive_recall, 6),
        "missingAttributeRecall": round(negative_recall, 6),
        "balancedAccuracy": round((positive_recall + negative_recall) / 2, 6),
        "worstClassRecall": round(min(positive_recall, negative_recall), 6),
        "correct": true_positive + true_negative,
        "cases": len(cases),
    }


def _select(
    rows: list[dict[str, Any]], selection_rule: dict[str, Any]
) -> dict[str, Any]:
    minimum_recall = float(selection_rule["answerableRecallAtLeast"])
    eligible = [row for row in rows if row["answerableRecall"] >= minimum_recall]
    if not eligible:
        raise ValueError("No threshold satisfies the pre-registered recall constraint.")
    return max(
        eligible,
        key=lambda row: (
            row["worstClassRecall"],
            row["balancedAccuracy"],
            row["missingAttributeRecall"],
            row["threshold"],
        ),
    )


def _slice_metrics(
    scored: list[dict[str, Any]], field: str, threshold: float
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in scored:
        grouped[str(case[field])].append(case)
    return {
        name: _metrics(items, threshold) for name, items in sorted(grouped.items())
    }


def _candidate_gate(
    selected: dict[str, Any],
    language_slices: dict[str, dict[str, Any]],
    category_slices: dict[str, dict[str, Any]],
    rule: dict[str, Any],
) -> dict[str, Any]:
    minimum_language = min(
        item["balancedAccuracy"] for item in language_slices.values()
    )
    topic_missing = category_slices["topic-related-missing"]["missingAttributeRecall"]
    checks = {
        "worstClassRecall": {
            "actual": selected["worstClassRecall"],
            "requiredAtLeast": rule["worstClassRecallAtLeast"],
            "passed": selected["worstClassRecall"]
            >= rule["worstClassRecallAtLeast"],
        },
        "topicRelatedMissingRecall": {
            "actual": topic_missing,
            "requiredAtLeast": rule["topicRelatedMissingRecallAtLeast"],
            "passed": topic_missing >= rule["topicRelatedMissingRecallAtLeast"],
        },
        "minimumLanguageBalancedAccuracy": {
            "actual": minimum_language,
            "requiredAtLeast": rule["minimumLanguageBalancedAccuracyAtLeast"],
            "passed": minimum_language
            >= rule["minimumLanguageBalancedAccuracyAtLeast"],
        },
    }
    return {
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate the experimental answerability verifier."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 48:
        raise ValueError("Answerability calibration requires at least 48 cases.")
    if sum(bool(case.get("answerable")) for case in cases) * 2 != len(cases):
        raise ValueError("Answerability calibration requires an exactly balanced dataset.")
    languages = {case.get("language") for case in cases}
    if languages != {"en", "zh"}:
        raise ValueError("Answerability calibration requires English and Chinese cases.")
    selection_rule = payload.get("selectionRule")
    candidate_gate_rule = payload.get("candidateGate")
    if not isinstance(selection_rule, dict) or not isinstance(
        candidate_gate_rule, dict
    ):
        raise ValueError("Dataset must pre-register selectionRule and candidateGate.")

    verifier = OnnxAnswerabilityVerifier.from_local_path(args.model_path)
    grouped_cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped_cases[case["query"]].append(case)
    scores_by_id: dict[str, float] = {}
    for query, items in grouped_cases.items():
        scores = verifier.score(query, [case["passage"] for case in items])
        if len(scores) != len(items):
            raise ValueError("Answerability verifier returned an unexpected score count.")
        scores_by_id.update(
            (case["id"], float(score))
            for case, score in zip(items, scores, strict=True)
        )
    scored = [
        {**case, "score": round(scores_by_id[case["id"]], 8)} for case in cases
    ]
    thresholds = selection_rule.get("thresholdGrid")
    if thresholds != {"start": 0.001, "stop": 0.999, "step": 0.001}:
        raise ValueError("Unexpected threshold grid.")
    rows = [_metrics(scored, index / 1000) for index in range(1, 1000)]
    selected = _select(rows, selection_rule)
    language_slices = _slice_metrics(
        scored, "language", selected["threshold"]
    )
    category_slices = _slice_metrics(
        scored, "category", selected["threshold"]
    )
    failures = [
        case
        for case in scored
        if (case["score"] >= selected["threshold"]) != case["answerable"]
    ]
    result = {
        "schemaVersion": 1,
        "dataset": {
            "path": str(args.dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            "split": "calibration-only",
        },
        "model": {
            "repository": verifier.spec.repository,
            "revision": verifier.spec.revision,
            "license": verifier.spec.license,
            "fileSha256": verifier.spec.file_sha256,
            "scoreDefinition": "entailment_probability + contradiction_probability",
        },
        "selectionRule": selection_rule,
        "selected": selected,
        "languageSlices": language_slices,
        "categorySlices": category_slices,
        "candidateGate": _candidate_gate(
            selected,
            language_slices,
            category_slices,
            candidate_gate_rule,
        ),
        "failures": failures,
        "cases": scored,
        "thresholdMetrics": rows,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
