from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_workbench.relevance import OnnxRelevanceVerifier


def _rate(value: int, total: int) -> float:
    return value / total if total else 0.0


def _metrics(cases: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    positives = [case for case in cases if case["relevant"]]
    negatives = [case for case in cases if not case["relevant"]]
    true_positive = sum(case["score"] >= threshold for case in positives)
    true_negative = sum(case["score"] < threshold for case in negatives)
    positive_recall = _rate(true_positive, len(positives))
    negative_recall = _rate(true_negative, len(negatives))
    return {
        "threshold": round(threshold, 2),
        "positiveRecall": round(positive_recall, 6),
        "negativeRecall": round(negative_recall, 6),
        "balancedAccuracy": round((positive_recall + negative_recall) / 2, 6),
        "worstClassRecall": round(min(positive_recall, negative_recall), 6),
        "correct": true_positive + true_negative,
        "cases": len(cases),
    }


def _select(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["positiveRecall"] >= 0.85]
    if not eligible:
        raise ValueError("No threshold satisfies the pre-registered recall constraint.")
    return max(
        eligible,
        key=lambda row: (
            row["worstClassRecall"],
            row["balancedAccuracy"],
            row["negativeRecall"],
            row["threshold"],
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate the relevance verifier.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 40:
        raise ValueError("Relevance calibration requires at least 40 cases.")
    if sum(bool(case.get("relevant")) for case in cases) != len(cases) // 2:
        raise ValueError("Relevance calibration requires an exactly balanced dataset.")
    verifier = OnnxRelevanceVerifier.from_local_path(args.model_path)
    scores = verifier.score(
        "", []
    )
    if scores:
        raise ValueError("Verifier returned scores for an empty batch.")
    scored: list[dict[str, Any]] = []
    for case in cases:
        score = verifier.score(case["query"], [case["passage"]])[0]
        scored.append({**case, "score": round(score, 8)})
    rows = [_metrics(scored, index / 100) for index in range(1, 100)]
    selected = _select(rows)
    slices: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in scored:
        grouped[case["language"]].append(case)
    for language, items in sorted(grouped.items()):
        slices[language] = _metrics(items, selected["threshold"])
    failures = [
        case
        for case in scored
        if (case["score"] >= selected["threshold"]) != case["relevant"]
    ]
    result = {
        "schemaVersion": 1,
        "dataset": {
            "path": str(args.dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            "split": "development",
        },
        "model": {
            "repository": verifier.spec.repository,
            "revision": verifier.spec.revision,
            "license": verifier.spec.license,
            "fileSha256": verifier.spec.file_sha256,
        },
        "selectionRule": payload.get("selectionRule"),
        "selected": selected,
        "languageSlices": slices,
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
