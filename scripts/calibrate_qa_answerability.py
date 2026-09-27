from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from agent_workbench.relevance import OnnxQaAnswerabilityVerifier


_NORMALIZE = re.compile(r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+")


def _normalize(value: str) -> str:
    return _NORMALIZE.sub("", value.lower())


def _answer_is_correct(answer: str, expected: list[str]) -> bool:
    normalized_answer = _normalize(answer)
    return bool(normalized_answer) and any(
        _normalize(value) in normalized_answer
        or normalized_answer in _normalize(value)
        for value in expected
        if _normalize(value)
    )


def _case_passage(case: dict[str, Any]) -> str:
    passage = case.get("passage")
    passages = case.get("passages")
    if isinstance(passage, str) and passage.strip() and passages is None:
        return passage
    if (
        isinstance(passages, list)
        and len(passages) >= 2
        and all(isinstance(value, str) and value.strip() for value in passages)
        and passage is None
    ):
        return "\n\n".join(
            f"Evidence {index}:\n{value}"
            for index, value in enumerate(passages, start=1)
        )
    raise ValueError("Each case must contain passage or at least two passages.")


def _rate(value: int, total: int) -> float | None:
    return round(value / total, 6) if total else None


def _metrics(cases: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    positives = [case for case in cases if case["answerable"]]
    negatives = [case for case in cases if not case["answerable"]]
    true_positive = sum(case["score"] >= threshold for case in positives)
    true_negative = sum(case["score"] < threshold for case in negatives)
    successful_answers = sum(
        case["score"] >= threshold and case["answerCorrect"] for case in positives
    )
    positive_recall = _rate(true_positive, len(positives))
    negative_recall = _rate(true_negative, len(negatives))
    available = [value for value in (positive_recall, negative_recall) if value is not None]
    return {
        "threshold": round(threshold, 3),
        "answerableRecall": positive_recall,
        "unanswerableRecall": negative_recall,
        "balancedAccuracy": (
            None if not available else round(sum(available) / len(available), 6)
        ),
        "worstClassRecall": None if not available else min(available),
        "answerSpanAccuracy": _rate(
            sum(case["answerCorrect"] for case in positives), len(positives)
        ),
        "successfulAnswerRecall": _rate(successful_answers, len(positives)),
        "correctClassification": true_positive + true_negative,
        "cases": len(cases),
    }


def _select(
    rows: list[dict[str, Any]], selection_rule: dict[str, Any]
) -> dict[str, Any]:
    minimum_recall = float(selection_rule["answerableRecallAtLeast"])
    eligible = [
        row
        for row in rows
        if row["answerableRecall"] is not None
        and row["answerableRecall"] >= minimum_recall
    ]
    if not eligible:
        raise ValueError("No threshold satisfies the pre-registered recall constraint.")
    return max(
        eligible,
        key=lambda row: (
            row["worstClassRecall"],
            row["balancedAccuracy"],
            row["unanswerableRecall"],
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
    topic_missing = category_slices["topic-related-missing"]["unanswerableRecall"]
    checks = {
        "worstClassRecall": {
            "actual": selected["worstClassRecall"],
            "requiredAtLeast": rule["worstClassRecallAtLeast"],
            "passed": selected["worstClassRecall"]
            >= rule["worstClassRecallAtLeast"],
        },
        "successfulAnswerRecall": {
            "actual": selected["successfulAnswerRecall"],
            "requiredAtLeast": rule["successfulAnswerRecallAtLeast"],
            "passed": selected["successfulAnswerRecall"]
            >= rule["successfulAnswerRecallAtLeast"],
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
        description="Calibrate the experimental extractive-QA answerability verifier."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 40:
        raise ValueError("QA answerability calibration requires at least 40 cases.")
    if sum(bool(case.get("answerable")) for case in cases) * 2 != len(cases):
        raise ValueError("QA answerability calibration requires a balanced dataset.")
    if {case.get("language") for case in cases} != {"en", "zh"}:
        raise ValueError("QA answerability calibration requires English and Chinese.")
    for case in cases:
        _case_passage(case)
        expected = case.get("expectedAnswers")
        if case["answerable"] and (
            not isinstance(expected, list)
            or not expected
            or not all(isinstance(value, str) and value.strip() for value in expected)
        ):
            raise ValueError("Every answerable case requires expectedAnswers.")
        if not case["answerable"] and expected != []:
            raise ValueError("Unanswerable cases must use an empty expectedAnswers list.")
    selection_rule = payload.get("selectionRule")
    candidate_gate_rule = payload.get("candidateGate")
    if not isinstance(selection_rule, dict) or not isinstance(
        candidate_gate_rule, dict
    ):
        raise ValueError("Dataset must pre-register selectionRule and candidateGate.")

    verifier = OnnxQaAnswerabilityVerifier.from_local_path(args.model_path)
    grouped_cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped_cases[case["query"]].append(case)
    assessments: dict[str, Any] = {}
    for query, items in grouped_cases.items():
        values = verifier.assess(query, [_case_passage(case) for case in items])
        if len(values) != len(items):
            raise ValueError("QA verifier returned an unexpected assessment count.")
        assessments.update(
            (case["id"], value)
            for case, value in zip(items, values, strict=True)
        )
    scored = []
    for case in cases:
        assessment = assessments[case["id"]]
        scored.append(
            {
                **case,
                "score": round(assessment.score, 8),
                "extractedAnswer": assessment.answer,
                "answerStart": assessment.start,
                "answerEnd": assessment.end,
                "answerCorrect": (
                    _answer_is_correct(assessment.answer, case["expectedAnswers"])
                    if case["answerable"]
                    else False
                ),
                "evidenceSetSize": len(case.get("passages", [case.get("passage")])),
            }
        )
    thresholds = selection_rule.get("thresholdGrid")
    if thresholds != {"start": 0.001, "stop": 0.999, "step": 0.001}:
        raise ValueError("Unexpected threshold grid.")
    rows = [_metrics(scored, index / 1000) for index in range(1, 1000)]
    selected = _select(rows, selection_rule)
    language_slices = _slice_metrics(scored, "language", selected["threshold"])
    category_slices = _slice_metrics(scored, "category", selected["threshold"])
    failures = [
        case
        for case in scored
        if (case["score"] >= selected["threshold"]) != case["answerable"]
        or (case["answerable"] and not case["answerCorrect"])
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
            "scoreDefinition": "sigmoid(best_context_span_logit - cls_null_logit)",
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
