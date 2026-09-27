from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import secrets
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from agent_workbench.agents import ResearchAgent, ResearchReport
from agent_workbench.runtime import AgentRuntime
from agent_workbench.supervisor import ResearchSupervisor
from agent_workbench.tools import build_default_registry
from agent_workbench.tracing import TraceStore
from agent_workbench.workspace import WorkspaceManager


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


def _score(case: dict[str, Any], report: ResearchReport) -> tuple[bool, str | None]:
    expected_paths = set(case["expectedPaths"])
    actual_paths = set(report.source_files)
    if case["kind"] == "synthesis":
        passed = actual_paths == expected_paths
        return passed, None if passed else "synthesis-source-coverage"
    if case["kind"] == "unsupported":
        passed = not report.citations and "cannot provide a source-grounded answer" in report.content
        return passed, None if passed else "unsupported-query-not-refused"
    cited_paths = {str(citation["path"]) for citation in report.citations}
    if not expected_paths.issubset(cited_paths):
        return False, "required-evidence-missing"
    return True, None


def _run_case(case: dict[str, Any], strategy: str, documents: list[dict[str, str]]) -> dict[str, Any]:
    with TemporaryDirectory(prefix=f"agent-workbench-{strategy}-") as directory:
        workspace = WorkspaceManager(Path(directory), secrets.token_bytes(32))
        context = workspace.create_project(
            "supervisor-benchmark", strategy, case["id"], "benchmark"
        )
        for document in documents:
            document_path = str(document["path"])
            relative_path = (
                document_path if document_path.startswith("inputs/") else f"inputs/{document_path}"
            )
            path = workspace.safe_content_path(context, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document["content"], encoding="utf-8")
        runtime = AgentRuntime(
            context,
            workspace,
            build_default_registry(),
            TraceStore(),
            max_steps=len(documents) + 4,
        )
        started = perf_counter()
        if strategy == "supervisor":
            supervised = ResearchSupervisor(runtime).run(
                case["task"], approve_write=True
            )
            report = supervised.report
            specialist = supervised.routing.specialist.value
        else:
            report = ResearchAgent(runtime).run(case["task"], approve_write=True)
            specialist = "single-research"
        duration_ms = round((perf_counter() - started) * 1000, 3)
        passed, failure_type = _score(case, report)
        cited_paths = {str(citation["path"]) for citation in report.citations}
        expected_paths = set(case["expectedPaths"])
        citation_precision = None
        if case["kind"] == "evidence":
            citation_precision = (
                len(cited_paths.intersection(expected_paths)) / len(cited_paths)
                if cited_paths
                else 0.0
            )
        elif case["kind"] == "unsupported":
            citation_precision = float(not cited_paths)
        routing_correct = specialist == case["expectedSpecialist"]
        if strategy == "supervisor" and not routing_correct and failure_type is None:
            failure_type = "wrong-specialist"
            passed = False
        return {
            "id": case["id"],
            "passed": passed,
            "failureType": failure_type,
            "language": case.get("language", "unspecified"),
            "category": case.get("category", case["kind"]),
            "specialist": specialist,
            "routingCorrect": routing_correct,
            "citationPrecision": (
                None if citation_precision is None else round(citation_precision, 6)
            ),
            "toolCalls": len(runtime.tool_events),
            "durationMs": duration_ms,
        }


def _slice_metrics(results: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result[field])].append(result)
    return {
        name: {
            "cases": len(items),
            "passed": sum(bool(item["passed"]) for item in items),
            "passRate": round(sum(bool(item["passed"]) for item in items) / len(items), 6),
        }
        for name, items in sorted(grouped.items())
    }


def _resolve_documents(payload: dict[str, Any], case: dict[str, Any]) -> list[dict[str, str]]:
    if "documents" in case:
        return case["documents"]
    corpus = payload.get("documents")
    selected = case.get("documentPaths")
    if not isinstance(corpus, list) or not isinstance(selected, list):
        raise ValueError(f"Case {case.get('id')} has no documents.")
    by_path = {document["path"]: document for document in corpus}
    missing = [path for path in selected if path not in by_path]
    if missing:
        raise ValueError(f"Case {case.get('id')} references missing documents: {missing}")
    return [by_path[path] for path in selected]


def evaluate(dataset: Path) -> dict[str, Any]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    document_dataset = payload.get("documentDataset")
    if document_dataset is not None:
        if not isinstance(document_dataset, str) or not document_dataset:
            raise ValueError("documentDataset must be a non-empty relative path.")
        document_path = (dataset.parent / document_dataset).resolve()
        if document_path.parent != dataset.parent.resolve():
            raise ValueError("documentDataset must remain in the benchmark directory.")
        document_payload = json.loads(document_path.read_text(encoding="utf-8"))
        payload["documents"] = document_payload["documents"]
    cases = payload["cases"]
    strategies: dict[str, Any] = {}
    for strategy in ("single", "supervisor"):
        case_results = [
            _run_case(case, strategy, _resolve_documents(payload, case)) for case in cases
        ]
        passed = sum(result["passed"] for result in case_results)
        citation_precisions = [
            result["citationPrecision"]
            for result in case_results
            if result["citationPrecision"] is not None
        ]
        strategies[strategy] = {
            "passed": passed,
            "cases": len(case_results),
            "successRate": round(passed / len(case_results), 6),
            "successRate95CI": _wilson_interval(passed, len(case_results)),
            "averageToolCalls": round(
                sum(result["toolCalls"] for result in case_results) / len(case_results),
                3,
            ),
            "averageDurationMs": round(
                sum(result["durationMs"] for result in case_results) / len(case_results),
                3,
            ),
            "averageCitationPrecision": round(
                sum(citation_precisions) / len(citation_precisions), 6
            ),
            "languageSlices": _slice_metrics(case_results, "language"),
            "categorySlices": _slice_metrics(case_results, "category"),
            "failures": [result for result in case_results if not result["passed"]],
            "caseResults": case_results,
        }
    return {
        "schemaVersion": 1,
        "dataset": {
            "path": str(dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "documentDataset": document_dataset,
        },
        "single": strategies["single"],
        "supervisor": strategies["supervisor"],
        "successRateDelta": round(
            strategies["supervisor"]["successRate"]
            - strategies["single"]["successRate"],
            6,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare the single research agent with the routed supervisor."
    )
    parser.add_argument(
        "--dataset", type=Path, default=Path("benchmarks/supervisor_cases.json")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-improvement", action="store_true")
    parser.add_argument("--minimum-cases", type=int, default=1)
    args = parser.parse_args()
    result = evaluate(args.dataset)
    if result["single"]["cases"] < args.minimum_cases:
        parser.error(
            f"Dataset has {result['single']['cases']} cases; at least {args.minimum_cases} are required."
        )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.require_improvement and not (
        result["supervisor"]["successRate"] > result["single"]["successRate"]
        and result["supervisor"]["averageToolCalls"]
        < result["single"]["averageToolCalls"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
