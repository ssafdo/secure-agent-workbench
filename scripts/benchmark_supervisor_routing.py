from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agent_workbench.supervisor import ResearchSupervisor

SPECIALISTS = {"retrieval", "synthesis"}
LANGUAGES = {"en", "zh"}


def _validate(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("Routing dataset must use schemaVersion 1.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 50:
        raise ValueError("Routing dataset must contain at least 50 cases.")
    ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Case {index} must be an object.")
        required = {"id", "language", "category", "task", "expectedSpecialist", "errorCost"}
        if set(case) != required:
            raise ValueError(f"Case {index} fields do not match the routing schema.")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError(f"Case {index} has an invalid or duplicate id.")
        ids.add(case_id)
        if case["language"] not in LANGUAGES:
            raise ValueError(f"Case {case_id} has an unsupported language.")
        if not isinstance(case["category"], str) or not case["category"]:
            raise ValueError(f"Case {case_id} has an invalid category.")
        if not isinstance(case["task"], str) or not case["task"].strip():
            raise ValueError(f"Case {case_id} has an empty task.")
        if case["expectedSpecialist"] not in SPECIALISTS:
            raise ValueError(f"Case {case_id} has an invalid specialist.")
        if not isinstance(case["errorCost"], int) or case["errorCost"] < 1:
            raise ValueError(f"Case {case_id} has an invalid error cost.")
    return cases


def _slice(results: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result[field])].append(result)
    return {
        name: {
            "cases": len(items),
            "correct": sum(item["correct"] for item in items),
            "accuracy": round(sum(item["correct"] for item in items) / len(items), 6),
        }
        for name, items in sorted(grouped.items())
    }


def evaluate(dataset: Path) -> dict[str, Any]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    cases = _validate(payload)
    results: list[dict[str, Any]] = []
    confusion = {
        expected: {actual: 0 for actual in sorted(SPECIALISTS)}
        for expected in sorted(SPECIALISTS)
    }
    confidence_counts: Counter[str] = Counter()
    weighted_error = 0
    total_weight = 0
    for case in cases:
        decision = ResearchSupervisor.route(case["task"])
        actual = decision.specialist.value
        expected = case["expectedSpecialist"]
        correct = actual == expected
        total_weight += case["errorCost"]
        if not correct:
            weighted_error += case["errorCost"]
        confusion[expected][actual] += 1
        confidence_counts[decision.confidence.value] += 1
        results.append(
            {
                "id": case["id"],
                "language": case["language"],
                "category": case["category"],
                "expected": expected,
                "actual": actual,
                "correct": correct,
                "errorCost": case["errorCost"],
                "confidence": decision.confidence.value,
                "reason": decision.reason,
                "synthesisSignals": decision.synthesis_signal_count,
                "retrievalSignals": decision.retrieval_signal_count,
            }
        )
    correct = sum(result["correct"] for result in results)
    conflict_results = [result for result in results if result["category"] == "conflict"]
    default_results = [result for result in results if result["category"] == "default"]
    return {
        "schemaVersion": 1,
        "dataset": {
            "path": str(dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        },
        "cases": len(results),
        "correct": correct,
        "accuracy": round(correct / len(results), 6),
        "weightedError": weighted_error,
        "weightedAccuracy": round(1 - (weighted_error / total_weight), 6),
        "confusionMatrix": confusion,
        "confidenceCounts": dict(sorted(confidence_counts.items())),
        "languageSlices": _slice(results, "language"),
        "categorySlices": _slice(results, "category"),
        "conflictCases": len(conflict_results),
        "conflictCorrect": sum(result["correct"] for result in conflict_results),
        "defaultCases": len(default_results),
        "lowConfidenceDefaults": sum(
            result["confidence"] == "low" for result in default_results
        ),
        "errors": [result for result in results if not result["correct"]],
        "caseResults": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure deterministic supervisor routing quality.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/supervisor_routing_cases.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-accuracy", type=float, default=0.96)
    parser.add_argument("--maximum-weighted-error", type=int, default=0)
    args = parser.parse_args()
    result = evaluate(args.dataset)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if (
        result["accuracy"] < args.minimum_accuracy
        or result["weightedError"] > args.maximum_weighted_error
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
