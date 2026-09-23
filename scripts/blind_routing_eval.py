from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPOSITORY_ROOT / "src"
ROUTER_SOURCE = SOURCE_ROOT / "agent_workbench" / "supervisor.py"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agent_workbench.supervisor import ResearchSupervisor

MANIFEST_KIND = "secure-agent-workbench/blind-routing-manifest"
SPECIALISTS = {"retrieval", "synthesis"}
LANGUAGES = {"en", "zh", "mixed", "other"}
CATEGORIES = {
    "evidence",
    "unsupported",
    "question",
    "synthesis",
    "comparison",
    "conflict",
    "default",
    "adversarial",
    "other",
}
REQUIRED_FIELDS = {
    "id",
    "language",
    "category",
    "task",
    "expectedSpecialist",
    "errorCost",
    "deidentified",
    "reviewedByHuman",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SENSITIVE_PATTERNS = (
    ("email-address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{12,}", re.IGNORECASE)),
    (
        "assigned-secret",
        re.compile(
            r"\b(?:api[_ -]?key|password|passwd|secret|access[_ -]?token)\b\s*[:=]\s*[^\s,;]{4,}",
            re.IGNORECASE,
        ),
    ),
    ("windows-user-path", re.compile(r"\b[A-Z]:\\Users\\[^\\\s]+", re.IGNORECASE)),
    ("posix-home-path", re.compile(r"/(?:home|Users)/[^/\s]+")),
    ("phone-number", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("long-token", re.compile(r"\b[A-Za-z0-9_-]{40,}\b")),
)
MAX_DATASET_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
MAX_TASK_CHARACTERS = 2000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sensitive_reason(task: str) -> str | None:
    for reason, pattern in SENSITIVE_PATTERNS:
        if pattern.search(task):
            return reason
    return None


def load_dataset(path: Path, minimum_cases: int = 20) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError("Blind dataset must be an existing file.")
    if path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("Blind dataset exceeds the 2 MiB limit.")
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("Blind dataset must be valid UTF-8.") from error
    for line_number, raw_line in enumerate(lines, 1):
        if not raw_line.strip():
            continue
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"Line {line_number} exceeds the 16 KiB limit.")
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Line {line_number} is not valid JSON.") from error
        if not isinstance(value, dict) or set(value) != REQUIRED_FIELDS:
            raise ValueError(f"Line {line_number} does not match the blind dataset schema.")
        case_id = value["id"]
        if not isinstance(case_id, str) or not ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"Line {line_number} has an invalid opaque id.")
        if case_id in ids:
            raise ValueError(f"Line {line_number} has a duplicate id.")
        ids.add(case_id)
        task = value["task"]
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARACTERS:
            raise ValueError(f"Case {case_id} has an invalid task length.")
        if value["deidentified"] is not True or value["reviewedByHuman"] is not True:
            raise ValueError(f"Case {case_id} requires deidentification and human review.")
        sensitive_reason = _sensitive_reason(task)
        if sensitive_reason is not None:
            raise ValueError(f"Case {case_id} failed the sensitive-data scan: {sensitive_reason}.")
        if not isinstance(value["language"], str) or value["language"] not in LANGUAGES:
            raise ValueError(f"Case {case_id} has an unsupported language.")
        if not isinstance(value["category"], str) or value["category"] not in CATEGORIES:
            raise ValueError(f"Case {case_id} has an unsupported category.")
        if (
            not isinstance(value["expectedSpecialist"], str)
            or value["expectedSpecialist"] not in SPECIALISTS
        ):
            raise ValueError(f"Case {case_id} has an invalid expected specialist.")
        error_cost = value["errorCost"]
        if not isinstance(error_cost, int) or isinstance(error_cost, bool) or not 1 <= error_cost <= 5:
            raise ValueError(f"Case {case_id} has an invalid error cost.")
        cases.append(value)
    if len(cases) < minimum_cases:
        raise ValueError(f"Blind dataset must contain at least {minimum_cases} cases.")
    return cases


def create_manifest(dataset: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": MANIFEST_KIND,
        "datasetSha256": _sha256(dataset),
        "routerSha256": _sha256(ROUTER_SOURCE),
        "cases": len(cases),
        "languageCounts": dict(sorted(Counter(case["language"] for case in cases).items())),
        "labelCounts": dict(
            sorted(Counter(case["expectedSpecialist"] for case in cases).items())
        ),
    }


def _counts(cases: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(case[field] for case in cases).items()))


def _unit_interval(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a number between 0 and 1") from error
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return parsed


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Blind manifest must be an existing file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Blind manifest is not valid UTF-8 JSON.") from error
    required = {
        "schemaVersion",
        "kind",
        "datasetSha256",
        "routerSha256",
        "cases",
        "languageCounts",
        "labelCounts",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Blind manifest has an invalid schema.")
    if value["schemaVersion"] != 1 or value["kind"] != MANIFEST_KIND:
        raise ValueError("Blind manifest has an unsupported version or kind.")
    if not isinstance(value["cases"], int) or isinstance(value["cases"], bool) or value["cases"] < 1:
        raise ValueError("Blind manifest has an invalid case count.")
    for field in ("datasetSha256", "routerSha256"):
        if not isinstance(value[field], str) or not SHA256_PATTERN.fullmatch(value[field]):
            raise ValueError(f"Blind manifest has an invalid {field}.")
    for field in ("languageCounts", "labelCounts"):
        counts = value[field]
        if (
            not isinstance(counts, dict)
            or not counts
            or any(
                not isinstance(name, str)
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
                for name, count in counts.items()
            )
        ):
            raise ValueError(f"Blind manifest has invalid {field}.")
    return value


def evaluate(
    dataset: Path,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    if manifest["datasetSha256"] != _sha256(dataset):
        raise ValueError("Blind dataset changed after it was sealed.")
    if manifest["routerSha256"] != _sha256(ROUTER_SOURCE):
        raise ValueError("Supervisor routing code changed after the dataset was sealed.")
    if manifest["cases"] != len(cases):
        raise ValueError("Blind manifest case count does not match the dataset.")
    if manifest["languageCounts"] != _counts(cases, "language"):
        raise ValueError("Blind manifest language distribution does not match the dataset.")
    if manifest["labelCounts"] != _counts(cases, "expectedSpecialist"):
        raise ValueError("Blind manifest label distribution does not match the dataset.")
    results: list[dict[str, Any]] = []
    weighted_error = 0
    total_weight = 0
    confusion = {
        expected: {actual: 0 for actual in sorted(SPECIALISTS)}
        for expected in sorted(SPECIALISTS)
    }
    slices: dict[str, list[bool]] = defaultdict(list)
    for case in cases:
        decision = ResearchSupervisor.route(case["task"])
        actual = decision.specialist.value
        expected = case["expectedSpecialist"]
        correct = actual == expected
        total_weight += case["errorCost"]
        if not correct:
            weighted_error += case["errorCost"]
        confusion[expected][actual] += 1
        slices[case["language"]].append(correct)
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
            }
        )
    correct = sum(result["correct"] for result in results)
    return {
        "schemaVersion": 1,
        "kind": "secure-agent-workbench/blind-routing-result",
        "datasetSha256": manifest["datasetSha256"],
        "routerSha256": manifest["routerSha256"],
        "cases": len(results),
        "correct": correct,
        "accuracy": round(correct / len(results), 6),
        "weightedError": weighted_error,
        "weightedErrorRate": round(weighted_error / total_weight, 6),
        "confusionMatrix": confusion,
        "languageSlices": {
            name: {
                "cases": len(values),
                "correct": sum(values),
                "accuracy": round(sum(values) / len(values), 6),
            }
            for name, values in sorted(slices.items())
        },
        "errors": [result for result in results if not result["correct"]],
        "caseResults": results,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal or evaluate a private blind routing dataset.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal")
    seal.add_argument("--dataset", type=Path, required=True)
    seal.add_argument("--manifest", type=Path, required=True)
    seal.add_argument("--minimum-cases", type=int, default=20)
    run = subparsers.add_parser("evaluate")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--minimum-cases", type=int, default=20)
    run.add_argument("--minimum-accuracy", type=_unit_interval, default=0.8)
    run.add_argument("--maximum-weighted-error-rate", type=_unit_interval, default=0.2)
    args = parser.parse_args()
    if args.minimum_cases < 1:
        raise ValueError("minimum-cases must be positive.")
    cases = load_dataset(args.dataset, args.minimum_cases)
    if args.command == "seal":
        manifest = create_manifest(args.dataset, cases)
        _write_json(args.manifest, manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    manifest = load_manifest(args.manifest)
    result = evaluate(args.dataset, manifest, cases)
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result["accuracy"] < args.minimum_accuracy
        or result["weightedErrorRate"] > args.maximum_weighted_error_rate
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
