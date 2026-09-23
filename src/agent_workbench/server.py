from __future__ import annotations

import json
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .agents import (
    HostedResearchAgent,
    ReActResearchAgent,
    ResearchAgent,
    RetrievalResearchAgent,
)
from .executor import ContainerExecutor
from .embeddings import EmbeddingConfiguration
from .modeling import (
    ModelCircuitOpen,
    ModelProtocolError,
    ModelProvider,
    ModelProviderError,
    ModelMessage,
)
from .models import WorkbenchError
from .runtime import AgentRuntime
from .sessions import SessionConflict, SessionExpired, SessionRecord, SessionStore
from .tools import build_default_registry
from .tracing import TraceStore
from .workspace import WorkspaceManager

MAX_REQUEST_BYTES = 2_000_000
MAX_SOURCES = 20
MAX_SOURCE_BYTES = 200_000
MAX_TASK_CHARS = 10_000
WEB_ROOT = Path(__file__).with_name("web")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class WorkbenchHTTPServer(ThreadingHTTPServer):
    workspace: WorkspaceManager
    hosted_provider: ModelProvider | None
    sessions: SessionStore
    container_executor: ContainerExecutor | None
    embedding: EmbeddingConfiguration


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server: WorkbenchHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _static_response(self, path: str) -> bool:
        route = STATIC_ROUTES.get(path)
        if route is None:
            return False
        filename, content_type = route
        body = (WEB_ROOT / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("x-frame-options", "DENY")
        self.send_header("referrer-policy", "no-referrer")
        self.send_header(
            "content-security-policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._json_response(HTTPStatus.OK, {"status": "ok"})
            return
        if self._static_response(path):
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/research":
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            request = self._read_request()
            response = self._run_research(request)
        except SessionConflict as error:
            self._json_response(
                HTTPStatus.CONFLICT,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except SessionExpired as error:
            self._json_response(
                HTTPStatus.GONE,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except ModelCircuitOpen as error:
            self._json_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except (ModelProviderError, ModelProtocolError) as error:
            self._json_response(
                HTTPStatus.BAD_GATEWAY,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except (KeyError, TypeError, ValueError, WorkbenchError) as error:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except Exception as error:
            self._json_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": type(error).__name__, "message": "Research execution failed."},
            )
            return
        self._json_response(HTTPStatus.OK, response)

    def _read_request(self) -> dict[str, Any]:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError("content-type must be application/json")
        raw_length = self.headers.get("content-length")
        if raw_length is None:
            raise ValueError("content-length is required")
        length = int(raw_length)
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ValueError(f"request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        return payload

    def _run_research(self, request: dict[str, Any]) -> dict[str, Any]:
        if not {"task", "sources"}.issubset(request) or not set(request).issubset(
            {"task", "sources", "engine", "sessionId", "expectedVersion"}
        ):
            raise ValueError(
                "request requires task and sources, with optional engine and session fields"
            )
        task = request["task"]
        sources = request["sources"]
        engine = request.get("engine", "deterministic")
        session_id = request.get("sessionId")
        expected_version = request.get("expectedVersion")
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
            raise ValueError(f"task must be a non-empty string up to {MAX_TASK_CHARS} characters")
        if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
            raise ValueError(f"sources must be an array with at most {MAX_SOURCES} entries")
        if engine not in {
            "deterministic",
            "retrieval",
            "react",
            "react-recovery",
            "hosted",
        }:
            raise ValueError(
                "engine must be deterministic, retrieval, react, react-recovery or hosted"
            )
        if session_id is None:
            if expected_version is not None:
                raise ValueError("expectedVersion requires sessionId.")
        else:
            if not isinstance(session_id, str):
                raise TypeError("sessionId must be a string.")
            self.server.sessions.validate_id(session_id)
            if expected_version is None:
                raise ValueError("sessionId requires expectedVersion.")
            if engine in {"deterministic", "retrieval"}:
                raise ValueError("sessions require react, react-recovery or hosted engine.")

        request_id = uuid.uuid4().hex
        conversation_id = session_id or request_id
        trace_session_id = session_id or request_id
        context = self.server.workspace.create_project(
            "research-api", "local-client", conversation_id, trace_session_id
        )
        with self.server.workspace.project_lock(context.project_id):
            session = (
                self.server.sessions.load(context, expected_version)
                if session_id is not None
                else None
            )
            response = self._execute_research(
                context, task, sources, engine, session
            )
            if session is not None:
                saved = self.server.sessions.save(
                    context,
                    session,
                    (
                        *session.history,
                        ModelMessage("user", task.strip()),
                        ModelMessage("assistant", response["report"]["content"]),
                    ),
                )
                response["session"] = saved.response()
            return response

    def _execute_research(
        self,
        context,
        task: str,
        sources: list[Any],
        engine: str,
        session: SessionRecord | None,
    ) -> dict[str, Any]:
        seen_paths: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "content"}:
                raise ValueError("each source requires exactly path and content")
            path = source["path"]
            content = source["content"]
            if not isinstance(path, str) or not isinstance(content, str):
                raise TypeError("source path and content must be strings")
            if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
                raise ValueError(
                    f"source content must not exceed {MAX_SOURCE_BYTES} UTF-8 bytes"
                )
            if path in seen_paths:
                raise ValueError(f"duplicate source path: {path}")
            seen_paths.add(path)
            target = self.server.workspace.safe_content_path(context, f"inputs/{path}")
            if target.suffix.lower() not in {".md", ".txt"}:
                raise ValueError("source files must use .md or .txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        runtime = AgentRuntime(
            context,
            self.server.workspace,
            build_default_registry(
                self.server.container_executor,
                self.server.embedding,
            ),
            TraceStore(),
            max_steps=MAX_SOURCES + 4,
        )
        if engine == "hosted":
            if self.server.hosted_provider is None:
                raise ValueError("hosted engine is not configured on this server")
            report = HostedResearchAgent(runtime, self.server.hosted_provider).run(
                task,
                approve_write=True,
                history=() if session is None else session.history,
            )
        elif engine in {"react", "react-recovery"}:
            report = ReActResearchAgent(
                runtime,
                task,
                inject_recoverable_failure=engine == "react-recovery",
            ).run(
                task,
                approve_write=True,
                history=() if session is None else session.history,
            )
        elif engine == "retrieval":
            report = RetrievalResearchAgent(runtime).run(task, approve_write=True)
        else:
            report = ResearchAgent(runtime).run(task, approve_write=True)
        return {
            "status": "completed",
            "engine": engine,
            "projectId": context.project_id,
            "report": {
                "artifactPath": report.artifact_path,
                "content": report.content,
                "sourceFiles": list(report.source_files),
                "citations": list(report.citations),
                **(
                    {}
                    if report.retrieval_mode is None
                    else {"retrievalMode": report.retrieval_mode}
                ),
            },
            "modelUsage": report.model_usage,
            "agentDiagnostics": {
                "contextCompactions": len(runtime.context_events),
                "compactedMessages": sum(
                    int(event["compactedMessages"])
                    for event in runtime.context_events
                ),
                "truncatedMessages": sum(
                    int(event["truncatedMessages"])
                    for event in runtime.context_events
                ),
                "reflections": len(runtime.reflection_events),
            },
            "actions": [
                {
                    "id": f"tool-{event['step']}",
                    "name": event["tool"],
                    "input": {"argumentKeys": event["argument_keys"]},
                    "status": event["status"],
                }
                for event in runtime.tool_events
            ],
        }


def create_server(
    workspace: WorkspaceManager,
    host: str = "127.0.0.1",
    port: int = 0,
    hosted_provider: ModelProvider | None = None,
    session_store: SessionStore | None = None,
    container_executor: ContainerExecutor | None = None,
    embedding: EmbeddingConfiguration | None = None,
) -> WorkbenchHTTPServer:
    server = WorkbenchHTTPServer((host, port), WorkbenchRequestHandler)
    server.workspace = workspace
    server.hosted_provider = hosted_provider
    server.sessions = session_store or SessionStore()
    server.container_executor = container_executor
    server.embedding = embedding or EmbeddingConfiguration()
    return server
