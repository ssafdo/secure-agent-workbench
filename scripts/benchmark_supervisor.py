from __future__ import annotations

import argparse
import hashlib
import json
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


def _score(case: dict[str, Any], report: ResearchReport) -> bool:
    expected_paths = set(case["expectedPaths"])
    actual_paths = set(report.source_files)
    if case["kind"] == "synthesis":
        return actual_paths == expected_paths
    if case["kind"] == "unsupported":
        return not report.citations and "cannot provide a source-grounded answer" in report.content
    cited_paths = {str(citation["path"]) for citation in report.citations}
    return expected_paths.issubset(cited_paths)


def _run_case(case: dict[str, Any], strategy: str) -> dict[str, Any]:
    with TemporaryDirectory(prefix=f"agent-workbench-{strategy}-") as directory:
        workspace = WorkspaceManager(Path(directory), secrets.token_bytes(32))
        context = workspace.create_project(
            "supervisor-benchmark", strategy, case["id"], "benchmark"
        )
        for document in case["documents"]:
            path = workspace.safe_content_path(context, f"inputs/{document['path']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document["content"], encoding="utf-8")
        runtime = AgentRuntime(
            context,
            workspace,
            build_default_registry(),
            TraceStore(),
            max_steps=len(case["documents"]) + 4,
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
        return {
            "id": case["id"],
            "passed": _score(case, report),
            "specialist": specialist,
            "routingCorrect": specialist == case["expectedSpecialist"],
            "toolCalls": len(runtime.tool_events),
            "durationMs": duration_ms,
        }


def evaluate(dataset: Path) -> dict[str, Any]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    cases = payload["cases"]
    strategies: dict[str, Any] = {}
    for strategy in ("single", "supervisor"):
        case_results = [_run_case(case, strategy) for case in cases]
        passed = sum(result["passed"] for result in case_results)
        strategies[strategy] = {
            "passed": passed,
            "cases": len(case_results),
            "successRate": round(passed / len(case_results), 6),
            "averageToolCalls": round(
                sum(result["toolCalls"] for result in case_results) / len(case_results),
                3,
            ),
            "averageDurationMs": round(
                sum(result["durationMs"] for result in case_results) / len(case_results),
                3,
            ),
            "caseResults": case_results,
        }
    return {
        "schemaVersion": 1,
        "dataset": {
            "path": str(dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
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
    args = parser.parse_args()
    result = evaluate(args.dataset)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.require_improvement and not (
        result["supervisor"]["successRate"] > result["single"]["successRate"]
        and result["supervisor"]["successRate"] == 1.0
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
