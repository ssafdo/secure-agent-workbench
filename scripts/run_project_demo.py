from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8767"


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={} if body is None else {"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(
            f"Cannot reach {base_url}. Start the workbench server before running the demo."
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object JSON response.")
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_demo(base_url: str) -> dict[str, Any]:
    health = request_json(base_url, "GET", "/health")
    require(health == {"status": "ok"}, "Health check did not return status=ok.")

    sources = [
        {
            "path": "migration-plan.md",
            "content": (
                "迁移采用分阶段发布。若新版本五分钟错误率超过 2%，立即回滚到稳定版本。\n"
                "API 密钥只能保存在服务端环境变量中，不得返回浏览器。"
            ),
        },
        {
            "path": "operations-notes.md",
            "content": (
                "灰度阶段先覆盖 10% 流量，并持续观察延迟。\n"
                "项目的主要风险是依赖服务限流和监控盲区。"
            ),
        },
    ]

    retrieval = request_json(
        base_url,
        "POST",
        "/v1/research",
        {
            "engine": "retrieval",
            "task": "哪份资料说明了回滚条件？请给出引用。",
            "sources": sources,
        },
    )
    citations = retrieval.get("report", {}).get("citations", [])
    require(retrieval.get("status") == "completed", "Retrieval scenario did not complete.")
    require(bool(citations), "Retrieval scenario returned no verified citation.")
    require(
        any(item.get("path") == "inputs/migration-plan.md" for item in citations),
        "Retrieval scenario did not cite migration-plan.md.",
    )

    retrieval_route = request_json(
        base_url,
        "POST",
        "/v1/research",
        {
            "engine": "supervisor",
            "task": "哪份资料说明了回滚条件？请给出引用。",
            "sources": sources,
        },
    )
    synthesis_route = request_json(
        base_url,
        "POST",
        "/v1/research",
        {
            "engine": "supervisor",
            "task": "比较两份资料并形成一份包含风险和建议的迁移简报。",
            "sources": sources,
        },
    )
    require(
        retrieval_route.get("routing", {}).get("specialist") == "retrieval",
        "Supervisor did not route the evidence query to retrieval.",
    )
    require(
        synthesis_route.get("routing", {}).get("specialist") == "synthesis",
        "Supervisor did not route the migration brief to synthesis.",
    )

    react = request_json(
        base_url,
        "POST",
        "/v1/research",
        {
            "engine": "react",
            "task": "根据资料生成迁移摘要并写入报告。",
            "sources": sources,
        },
    )
    action_names = [item.get("name") for item in react.get("actions", [])]
    require(react.get("status") == "completed", "ReAct scenario did not complete.")
    require(
        action_names == ["list_files", "read_text", "read_text", "write_text"],
        f"ReAct tool sequence changed unexpectedly: {action_names}",
    )
    require(
        react.get("modelUsage", {}).get("calls") == 4,
        "ReAct scenario did not report the expected four offline model calls.",
    )

    return {
        "schemaVersion": 1,
        "status": "passed",
        "baseUrl": base_url.rstrip("/"),
        "scenarios": {
            "retrievalCitation": {
                "passed": True,
                "projectId": retrieval["projectId"],
                "retrievalMode": retrieval["report"].get("retrievalMode"),
                "citations": citations,
            },
            "supervisorRouting": {
                "passed": True,
                "retrieval": retrieval_route["routing"],
                "synthesis": synthesis_route["routing"],
            },
            "offlineReAct": {
                "passed": True,
                "projectId": react["projectId"],
                "actions": action_names,
                "modelUsage": react["modelUsage"],
            },
        },
        "deepSeekEvidence": {
            "mode": "existing-niceeval-run",
            "runId": "c642a27e-f821-4d14-afef-cda5288d0765",
            "note": "This deterministic project demo does not call an external model.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed, offline project demo against a local workbench server."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/demo/project-demo.json"),
    )
    args = parser.parse_args()
    try:
        result = run_demo(args.base_url)
    except RuntimeError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Evidence: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
