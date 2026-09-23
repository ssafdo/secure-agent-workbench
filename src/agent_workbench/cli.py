from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from .agents import ResearchAgent
from .executor import ContainerConfigurationError, ContainerExecutor, container_doctor
from .models import Permission, ToolStatus
from .providers import (
    DeepSeekResponsesProvider,
    OpenAIResponsesProvider,
    ResilientModelProvider,
)
from .runtime import AgentRuntime
from .server import create_server
from .tools import build_default_registry
from .tracing import TraceStore
from .workspace import WorkspaceManager

DEV_SECRET = "development-only-secret-change-me"


def _default_docker_binary() -> str:
    configured = os.getenv("AGENT_WORKBENCH_DOCKER_BINARY", "").strip()
    if configured:
        return configured
    windows_path = Path(
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    )
    if windows_path.exists():
        return str(windows_path)
    return "docker"


def _container_environment() -> tuple[bool, str | None, tuple[str, ...], str]:
    raw_enabled = os.getenv("AGENT_WORKBENCH_CONTAINER_ENABLED", "").strip().lower()
    if raw_enabled not in {"", "0", "false", "1", "true"}:
        raise SystemExit(
            "AGENT_WORKBENCH_CONTAINER_ENABLED must be true/false or 1/0."
        )
    enabled = raw_enabled in {"1", "true"}
    image = os.getenv("AGENT_WORKBENCH_CONTAINER_IMAGE") or None
    executables = tuple(
        item.strip()
        for item in os.getenv("AGENT_WORKBENCH_CONTAINER_EXECUTABLES", "").split(",")
        if item.strip()
    )
    docker_binary = _default_docker_binary()
    if not docker_binary:
        raise SystemExit("AGENT_WORKBENCH_DOCKER_BINARY cannot be empty.")
    return enabled, image, executables, docker_binary


def _container_executor() -> ContainerExecutor | None:
    enabled, image, executables, docker_binary = _container_environment()
    if not enabled:
        return None
    if image is None or not executables:
        raise SystemExit(
            "Enabled container execution requires AGENT_WORKBENCH_CONTAINER_IMAGE "
            "and AGENT_WORKBENCH_CONTAINER_EXECUTABLES."
        )
    try:
        return ContainerExecutor(
            image, executables, docker_binary=docker_binary
        )
    except ContainerConfigurationError as error:
        raise SystemExit(str(error)) from error


def _workspace() -> WorkspaceManager:
    root = Path(os.getenv("AGENT_WORKBENCH_ROOT", "runtime"))
    secret = os.getenv("AGENT_WORKBENCH_SECRET", DEV_SECRET).encode("utf-8")
    return WorkspaceManager(root, secret)


def _create_runtime(
    workspace: WorkspaceManager,
    feature: str,
    user: str,
    conversation: str,
    session: str,
) -> AgentRuntime:
    context = workspace.create_project(feature, user, conversation, session)
    return AgentRuntime(context, workspace, build_default_registry(), TraceStore())


def _hosted_provider() -> ResilientModelProvider | None:
    provider_kind = os.getenv("AGENT_WORKBENCH_MODEL_PROVIDER", "responses").strip().lower()
    if provider_kind not in {"responses", "deepseek"}:
        raise SystemExit(
            "AGENT_WORKBENCH_MODEL_PROVIDER must be responses or deepseek."
        )
    if provider_kind == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        model = os.getenv("DEEPSEEK_MODEL")
        if not api_key or not model:
            raise SystemExit(
                "DeepSeek hosted engine requires DEEPSEEK_API_KEY and DEEPSEEK_MODEL."
            )
        try:
            timeout = float(os.getenv("AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS", "30"))
        except ValueError as error:
            raise SystemExit(
                "AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS must be numeric."
            ) from error
        return ResilientModelProvider(
            DeepSeekResponsesProvider(
                api_key=api_key,
                model=model,
                base_url=os.getenv(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                ),
                timeout_seconds=timeout,
            )
        )

    api_key = os.getenv("AGENT_WORKBENCH_MODEL_API_KEY")
    model = os.getenv("AGENT_WORKBENCH_MODEL")
    if api_key is None and model is None:
        return None
    if not api_key or not model:
        raise SystemExit(
            "Hosted engine requires AGENT_WORKBENCH_MODEL_API_KEY and AGENT_WORKBENCH_MODEL."
        )
    try:
        timeout = float(os.getenv("AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS", "30"))
    except ValueError as error:
        raise SystemExit("AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS must be numeric.") from error
    provider = OpenAIResponsesProvider(
        api_key=api_key,
        model=model,
        base_url=os.getenv(
            "AGENT_WORKBENCH_MODEL_BASE_URL", "https://api.openai.com/v1"
        ),
        timeout_seconds=timeout,
    )
    return ResilientModelProvider(provider)


def demo(args: argparse.Namespace) -> int:
    workspace = _workspace()
    session = args.session or f"demo-{secrets.token_hex(4)}"
    runtime = _create_runtime(workspace, "research", args.user, args.conversation, session)

    seed_files = {
        "inputs/architecture.md": (
            "The platform needs project isolation, tool allowlists, execution traces, "
            "and a controlled attachment bridge. Container isolation is planned."
        ),
        "inputs/agent-notes.txt": (
            "Start with a measurable single-agent baseline. Add ReAct, memory, RAG, "
            "MCP and multi-agent routing only after regression evals exist."
        ),
    }
    for path, content in seed_files.items():
        input_path = workspace.safe_content_path(runtime.context, path)
        input_path.write_text(content, encoding="utf-8")

    report = ResearchAgent(runtime).run(args.task, approve_write=True)
    trace_path = TraceStore().path_for(runtime.context)
    print(f"Project ID: {runtime.context.project_id}")
    print(f"Workspace:  {runtime.context.root}")
    print(f"Artifact:   {report.artifact_path}")
    print(f"Trace:      {trace_path}")
    print("\n" + report.content)
    if os.getenv("AGENT_WORKBENCH_SECRET") is None:
        print("WARNING: using the development secret; set AGENT_WORKBENCH_SECRET for deployment.")
    return 0


def list_projects(_: argparse.Namespace) -> int:
    for project_id in _workspace().list_project_ids():
        print(project_id)
    return 0


def inspect_project(args: argparse.Namespace) -> int:
    workspace = _workspace()
    if not re.fullmatch(r"[0-9a-f]{32}", args.project_id):
        raise SystemExit("Invalid project ID.")
    root = (workspace.projects_root / args.project_id).resolve()
    try:
        root.relative_to(workspace.projects_root)
    except ValueError as error:
        raise SystemExit("Invalid project ID.") from error
    if not root.is_dir():
        raise SystemExit(f"Project not found: {args.project_id}")
    metadata = root / ".agent" / "metadata.json"
    print(metadata.read_text(encoding="utf-8"))
    for path in sorted(root.rglob("*")):
        if path.is_file():
            print(str(path.relative_to(root)).replace("\\", "/"))
    return 0


def serve(args: argparse.Namespace) -> int:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The development API may only bind to loopback.")
    server = create_server(
        _workspace(),
        args.host,
        args.port,
        hosted_provider=_hosted_provider(),
        container_executor=_container_executor(),
    )
    host, port = server.server_address[:2]
    print(json.dumps({"status": "ready", "host": host, "port": port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def diagnose_container(_: argparse.Namespace) -> int:
    enabled, image, executables, docker_binary = _container_environment()
    facts = container_doctor(
        enabled=enabled,
        image=image,
        allowed_executables=executables,
        docker_binary=docker_binary,
    )
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0 if facts["ready"] else 1


def smoke_container(_: argparse.Namespace) -> int:
    enabled, image, executables, docker_binary = _container_environment()
    facts = container_doctor(
        enabled=enabled,
        image=image,
        allowed_executables=executables,
        docker_binary=docker_binary,
    )
    payload: dict[str, object] = {"status": "failed", "doctor": facts}
    if not facts["ready"]:
        payload["error"] = "Container executor is not ready."
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    if "agent-runner" not in executables:
        payload["error"] = "Container smoke requires agent-runner in the allowlist."
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    executor = _container_executor()
    if executor is None:
        payload["error"] = "Container executor is disabled."
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    with TemporaryDirectory(prefix="agent-workbench-container-smoke-") as directory:
        workspace = WorkspaceManager(Path(directory), secrets.token_bytes(32))
        base_context = workspace.create_project(
            "container", "local", "smoke", "smoke"
        )
        context = replace(
            base_context,
            allowed_permissions=frozenset(
                {Permission.READ, Permission.WRITE, Permission.EXECUTE}
            ),
        )
        (context.root / "inputs" / "container-smoke.txt").write_text(
            "phase-8-real", encoding="utf-8"
        )
        runtime = AgentRuntime(
            context,
            workspace,
            build_default_registry(executor),
            TraceStore(),
        )
        result = runtime.call(
            "container_exec", {"argv": ["agent-runner"]}, approved=True
        )
        artifact_path = context.root / "outputs" / "container-smoke.txt"
        artifact = (
            artifact_path.read_text(encoding="utf-8")
            if artifact_path.exists()
            else None
        )

    residual = subprocess.run(
        [
            docker_binary,
            "ps",
            "-a",
            "--filter",
            "name=agent-workbench-",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    residual_names = [line for line in residual.stdout.splitlines() if line.strip()]
    succeeded = (
        result.status is ToolStatus.SUCCEEDED
        and isinstance(result.output, dict)
        and result.output.get("exit_code") == 0
        and result.output.get("stdout") == "container-smoke-ok\n"
        and result.output.get("stdout_truncated") is False
        and result.output.get("stderr_truncated") is False
        and artifact == "isolated:phase-8-real"
        and residual.returncode == 0
        and not residual_names
    )
    payload.update(
        {
            "status": "completed" if succeeded else "failed",
            "toolStatus": result.status.value,
            "container": result.output,
            "artifact": artifact,
            "residualContainers": residual_names,
            "traceEvents": len(runtime.tool_events),
        }
    )
    if result.error is not None:
        payload["error"] = result.error
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if succeeded else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secure Agent Workbench")
    subparsers = parser.add_subparsers(required=True)

    demo_parser = subparsers.add_parser("demo", help="Run the deterministic research demo.")
    demo_parser.add_argument("--user", default="intern")
    demo_parser.add_argument("--conversation", default="first-project")
    demo_parser.add_argument("--session")
    demo_parser.add_argument(
        "--task", default="Summarize the first implementation priorities and risks."
    )
    demo_parser.set_defaults(handler=demo)

    list_parser = subparsers.add_parser("list-projects", help="List local project IDs.")
    list_parser.set_defaults(handler=list_projects)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one local project.")
    inspect_parser.add_argument("--project-id", required=True)
    inspect_parser.set_defaults(handler=inspect_project)

    serve_parser = subparsers.add_parser("serve", help="Run the loopback research API.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(handler=serve)

    doctor_parser = subparsers.add_parser(
        "container-doctor", help="Report container executor readiness as JSON."
    )
    doctor_parser.set_defaults(handler=diagnose_container)

    smoke_parser = subparsers.add_parser(
        "container-smoke", help="Run the fixed end-to-end container isolation smoke test."
    )
    smoke_parser.set_defaults(handler=smoke_container)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
