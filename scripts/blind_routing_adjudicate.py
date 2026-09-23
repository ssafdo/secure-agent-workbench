from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.blind_routing_eval import (
    CATEGORIES,
    ID_PATTERN,
    LANGUAGES,
    MAX_DATASET_BYTES,
    MAX_LINE_BYTES,
    MAX_TASK_CHARACTERS,
    SPECIALISTS,
    _sensitive_reason,
    _unit_interval,
)

CANDIDATE_FIELDS = {
    "id",
    "language",
    "task",
    "deidentified",
    "reviewedByHuman",
}
ANNOTATION_FIELDS = {
    "schemaVersion",
    "kind",
    "candidateSha256",
    "reviewerId",
    "labels",
}
ANNOTATION_KIND = "secure-agent-workbench/blind-routing-annotations"
LABEL_FIELDS = {"id", "category", "expectedSpecialist", "errorCost"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_utf8(path: Path, description: str) -> str:
    if not path.is_file():
        raise ValueError(f"{description} must be an existing file.")
    if path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError(f"{description} exceeds the 2 MiB limit.")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{description} must be valid UTF-8.") from error


def load_candidates(path: Path, minimum_cases: int = 20) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    ids: set[str] = set()
    for line_number, raw_line in enumerate(
        _read_utf8(path, "Candidate dataset").splitlines(), 1
    ):
        if not raw_line.strip():
            continue
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"Candidate line {line_number} exceeds the 16 KiB limit.")
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Candidate line {line_number} is not valid JSON.") from error
        if not isinstance(value, dict) or set(value) != CANDIDATE_FIELDS:
            raise ValueError(f"Candidate line {line_number} does not match the schema.")
        case_id = value["id"]
        if not isinstance(case_id, str) or not ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"Candidate line {line_number} has an invalid opaque id.")
        if case_id in ids:
            raise ValueError(f"Candidate line {line_number} has a duplicate id.")
        ids.add(case_id)
        task = value["task"]
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARACTERS:
            raise ValueError(f"Candidate {case_id} has an invalid task length.")
        if value["deidentified"] is not True or value["reviewedByHuman"] is not True:
            raise ValueError(f"Candidate {case_id} requires deidentification and human review.")
        reason = _sensitive_reason(task)
        if reason is not None:
            raise ValueError(f"Candidate {case_id} failed the sensitive-data scan: {reason}.")
        if not isinstance(value["language"], str) or value["language"] not in LANGUAGES:
            raise ValueError(f"Candidate {case_id} has an unsupported language.")
        candidates.append(value)
    if len(candidates) < minimum_cases:
        raise ValueError(f"Candidate dataset must contain at least {minimum_cases} cases.")
    return candidates


def load_annotations(
    path: Path, expected_ids: set[str], candidate_sha256: str
) -> dict[str, Any]:
    try:
        value = json.loads(_read_utf8(path, "Annotation file"))
    except json.JSONDecodeError as error:
        raise ValueError("Annotation file is not valid JSON.") from error
    if not isinstance(value, dict) or set(value) != ANNOTATION_FIELDS:
        raise ValueError("Annotation file does not match the schema.")
    reviewer_id = value["reviewerId"]
    if (
        value["schemaVersion"] != 1
        or value["kind"] != ANNOTATION_KIND
        or value["candidateSha256"] != candidate_sha256
        or not isinstance(reviewer_id, str)
        or not ID_PATTERN.fullmatch(reviewer_id)
        or not isinstance(value["labels"], list)
    ):
        raise ValueError("Annotation metadata or candidate hash is invalid.")
    labels: dict[str, dict[str, Any]] = {}
    for item in value["labels"]:
        if not isinstance(item, dict) or set(item) != LABEL_FIELDS:
            raise ValueError("An annotation label does not match the schema.")
        case_id = item["id"]
        if (
            not isinstance(case_id, str)
            or not ID_PATTERN.fullmatch(case_id)
            or case_id in labels
        ):
            raise ValueError("Annotation ids must be valid and unique.")
        if (
            not isinstance(item["expectedSpecialist"], str)
            or item["expectedSpecialist"] not in SPECIALISTS
        ):
            raise ValueError(f"Annotation {case_id} has an invalid specialist.")
        if not isinstance(item["category"], str) or item["category"] not in CATEGORIES:
            raise ValueError(f"Annotation {case_id} has an invalid category.")
        cost = item["errorCost"]
        if not isinstance(cost, int) or isinstance(cost, bool) or not 1 <= cost <= 5:
            raise ValueError(f"Annotation {case_id} has an invalid error cost.")
        labels[case_id] = item
    if set(labels) != expected_ids:
        raise ValueError("Annotation ids must exactly match the required candidate ids.")
    return {
        "candidateSha256": candidate_sha256,
        "kind": ANNOTATION_KIND,
        "reviewerId": reviewer_id,
        "labels": labels,
    }


def _cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    observed = sum(a == b for a, b in zip(labels_a, labels_b, strict=True)) / len(labels_a)
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum(
        counts_a[label] / len(labels_a) * counts_b[label] / len(labels_b)
        for label in SPECIALISTS
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return round((observed - expected) / (1 - expected), 6)


def compare_annotations(
    candidates_path: Path,
    candidates: list[dict[str, Any]],
    annotation_paths: tuple[Path, Path],
    annotations: tuple[dict[str, Any], dict[str, Any]],
) -> dict[str, Any]:
    first, second = annotations
    if first["reviewerId"] == second["reviewerId"]:
        raise ValueError("The two primary annotation files must use distinct reviewer ids.")
    ids = [candidate["id"] for candidate in candidates]
    specialist_a = [first["labels"][case_id]["expectedSpecialist"] for case_id in ids]
    specialist_b = [second["labels"][case_id]["expectedSpecialist"] for case_id in ids]
    specialist_agreed = sum(a == b for a, b in zip(specialist_a, specialist_b, strict=True))
    category_agreed = sum(
        first["labels"][case_id]["category"] == second["labels"][case_id]["category"]
        for case_id in ids
    )
    cost_agreed = sum(
        first["labels"][case_id]["errorCost"] == second["labels"][case_id]["errorCost"]
        for case_id in ids
    )
    conflicts = []
    for case_id in ids:
        fields = [
            field
            for field in ("category", "expectedSpecialist", "errorCost")
            if first["labels"][case_id][field] != second["labels"][case_id][field]
        ]
        if fields:
            conflicts.append({"id": case_id, "fields": fields})
    return {
        "schemaVersion": 1,
        "kind": "secure-agent-workbench/blind-routing-annotation-report",
        "candidateSha256": _sha256(candidates_path),
        "annotationSha256": [_sha256(path) for path in annotation_paths],
        "cases": len(ids),
        "primaryReviewers": 2,
        "categoryAgreement": round(category_agreed / len(ids), 6),
        "specialistAgreement": round(specialist_agreed / len(ids), 6),
        "errorCostAgreement": round(cost_agreed / len(ids), 6),
        "cohenKappa": _cohen_kappa(specialist_a, specialist_b),
        "conflicts": conflicts,
    }


def build_consensus_dataset(
    candidates: list[dict[str, Any]],
    primary: tuple[dict[str, Any], dict[str, Any]],
    report: dict[str, Any],
    adjudication: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    first, second = primary
    reviewer_ids = {first["reviewerId"], second["reviewerId"]}
    conflict_ids = {item["id"] for item in report["conflicts"]}
    if conflict_ids:
        if adjudication is None:
            raise ValueError("Annotation disagreements require an independent adjudication file.")
        if adjudication["reviewerId"] in reviewer_ids:
            raise ValueError("The adjudicator must be distinct from both primary reviewers.")
        if set(adjudication["labels"]) != conflict_ids:
            raise ValueError("Adjudication ids must exactly match the disagreement ids.")
    elif adjudication is not None:
        raise ValueError("An adjudication file is not allowed when there are no disagreements.")
    conflict_fields = {
        item["id"]: set(item["fields"])
        for item in report["conflicts"]
    }
    if adjudication is not None:
        for case_id, fields in conflict_fields.items():
            for field in ("category", "expectedSpecialist", "errorCost"):
                if (
                    field not in fields
                    and adjudication["labels"][case_id][field]
                    != first["labels"][case_id][field]
                ):
                    raise ValueError("Adjudication cannot change fields agreed by both reviewers.")
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        case_id = candidate["id"]
        label = (
            adjudication["labels"][case_id]
            if case_id in conflict_ids and adjudication is not None
            else first["labels"][case_id]
        )
        output.append(
            {
                **candidate,
                "category": label["category"],
                "expectedSpecialist": label["expectedSpecialist"],
                "errorCost": label["errorCost"],
            }
        )
    return output


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(value, ensure_ascii=False) for value in values) + "\n",
        encoding="utf-8",
    )


def _require_private_path(path: Path) -> None:
    resolved = path.resolve()
    roots = (
        (REPOSITORY_ROOT / "benchmarks" / "private").resolve(),
        (REPOSITORY_ROOT / "artifacts" / "private").resolve(),
    )
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError("Blind annotation files must stay in a repository private directory.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare independent private routing labels and build an adjudicated dataset."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--annotation-a", type=Path, required=True)
    parser.add_argument("--annotation-b", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minimum-cases", type=int, default=20)
    parser.add_argument("--minimum-category-agreement", type=_unit_interval, default=0.8)
    parser.add_argument("--minimum-specialist-agreement", type=_unit_interval, default=0.8)
    parser.add_argument("--minimum-error-cost-agreement", type=_unit_interval, default=0.8)
    args = parser.parse_args()
    if args.minimum_cases < 1:
        raise ValueError("minimum-cases must be positive.")
    private_paths = [
        args.candidates,
        args.annotation_a,
        args.annotation_b,
        args.dataset,
        args.report,
    ]
    if args.adjudication is not None:
        private_paths.append(args.adjudication)
    for path in private_paths:
        _require_private_path(path)
    candidates = load_candidates(args.candidates, args.minimum_cases)
    expected_ids = {candidate["id"] for candidate in candidates}
    candidate_sha256 = _sha256(args.candidates)
    paths = (args.annotation_a, args.annotation_b)
    primary = tuple(
        load_annotations(path, expected_ids, candidate_sha256) for path in paths
    )
    report = compare_annotations(args.candidates, candidates, paths, primary)
    _write_json(args.report, report)
    if (
        report["categoryAgreement"] < args.minimum_category_agreement
        or report["specialistAgreement"] < args.minimum_specialist_agreement
        or report["errorCostAgreement"] < args.minimum_error_cost_agreement
    ):
        print(json.dumps({**report, "conflicts": report["conflicts"]}, ensure_ascii=False, indent=2))
        return 1
    adjudication = None
    if args.adjudication is not None:
        conflict_ids = {item["id"] for item in report["conflicts"]}
        adjudication = load_annotations(
            args.adjudication, conflict_ids, candidate_sha256
        )
    try:
        dataset = build_consensus_dataset(candidates, primary, report, adjudication)
    except ValueError as error:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(str(error), file=sys.stderr)
        return 2
    _write_jsonl(args.dataset, dataset)
    print(
        json.dumps(
            {
                "cases": len(dataset),
                "categoryAgreement": report["categoryAgreement"],
                "specialistAgreement": report["specialistAgreement"],
                "errorCostAgreement": report["errorCostAgreement"],
                "cohenKappa": report["cohenKappa"],
                "adjudicatedCases": len(report["conflicts"]),
                "dataset": str(args.dataset),
                "report": str(args.report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
