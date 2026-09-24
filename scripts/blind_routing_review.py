from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.blind_routing_adjudicate import (
    _require_private_path,
    load_annotations,
    load_candidates,
)
from scripts.blind_routing_eval import CATEGORIES, ID_PATTERN, SPECIALISTS

MAX_BODY_BYTES = 32 * 1024
REVIEW_KIND = "secure-agent-workbench/blind-routing-annotations"
HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Private routing review</title>
  <style>
    :root { color: #202226; background: #f2f4f6; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; min-height: 100vh; }
    main { width: min(860px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 48px; }
    header { display: flex; justify-content: space-between; gap: 20px; align-items: end; border-bottom: 1px solid #d8dce1; padding-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .eyebrow { margin: 0 0 8px; color: #1769e0; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
    .progress { color: #5e6670; font-size: 13px; white-space: nowrap; }
    .panel { margin-top: 24px; padding: 24px; background: #fff; border: 1px solid #d8dce1; border-radius: 8px; box-shadow: 0 8px 24px rgba(24, 33, 45, .06); }
    .task-meta { display: flex; justify-content: space-between; gap: 16px; color: #69717b; font-size: 12px; }
    .task { min-height: 150px; margin: 18px 0 26px; padding: 18px; color: #17191d; background: #f7f8f9; border: 1px solid #e0e3e7; border-radius: 6px; white-space: pre-wrap; line-height: 1.65; }
    .translation-wrap { margin: -10px 0 26px; padding-top: 16px; border-top: 1px solid #e0e3e7; }
    .translation-label { margin: 0 0 8px; color: #69717b; font-size: 12px; font-weight: 700; }
    .translation { margin: 0; padding: 16px 18px; color: #29313a; background: #f6f9ff; border-left: 3px solid #1769e0; white-space: pre-wrap; line-height: 1.65; }
    .fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
    label { display: grid; gap: 7px; color: #59616b; font-size: 12px; font-weight: 700; }
    select, button { min-height: 40px; padding: 0 11px; font: inherit; border: 1px solid #c9ced5; border-radius: 5px; background: #fff; }
    select:focus, button:focus { outline: 3px solid rgba(23, 105, 224, .2); outline-offset: 1px; }
    .actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 24px; }
    .actions div { display: flex; gap: 8px; }
    button { cursor: pointer; color: #29313a; }
    button.primary { color: #fff; background: #1769e0; border-color: #1769e0; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    .notice { min-height: 22px; margin-top: 14px; color: #16794d; font-size: 13px; }
    .notice.error { color: #b63835; }
    .done { color: #16794d; font-weight: 700; }
    @media (max-width: 680px) { header { display: block; } .progress { display: block; margin-top: 10px; } .fields { grid-template-columns: 1fr; } .panel { padding: 18px; } .actions { align-items: stretch; flex-direction: column; } .actions div { width: 100%; } .actions button { flex: 1; } }
  </style>
</head>
<body>
<main>
  <header><div><p class="eyebrow">PRIVATE ROUTING REVIEW</p><h1>自然任务独立标注</h1></div><div id="progress" class="progress">连接中</div></header>
  <section class="panel">
    <div class="task-meta"><span id="case-id">—</span><span id="language">—</span></div>
    <div id="task" class="task">正在读取私有候选任务…</div>
    <div id="translation-wrap" class="translation-wrap" hidden><p class="translation-label">中文辅助译文（原文仍是评估输入）</p><p id="translation" class="translation"></p></div>
    <div class="fields">
      <label>类别<select id="category"><option value="evidence">evidence（证据定位）</option><option value="unsupported">unsupported（资料无依据）</option><option value="question">question（普通问答）</option><option value="synthesis">synthesis（综合总结）</option><option value="comparison">comparison（比较异同）</option><option value="conflict">conflict（目标或资料冲突）</option><option value="default">default（开放任务）</option><option value="adversarial">adversarial（操纵路由）</option><option value="other">other（其他）</option></select></label>
      <label>专业 Agent<select id="specialist"><option value="retrieval">retrieval（检索与核实）</option><option value="synthesis">synthesis（总结与整合）</option></select></label>
      <label>错误成本<select id="error-cost"><option value="1">1（轻微）</option><option value="2">2（中等）</option><option value="3">3（较高）</option><option value="4">4（高）</option><option value="5">5（严重）</option></select></label>
    </div>
    <div class="actions"><div><button id="previous" type="button">上一条</button><button id="next" type="button">下一条</button></div><button id="save" class="primary" type="button">保存这条</button></div>
    <div id="notice" class="notice" role="status" aria-live="polite"></div>
  </section>
</main>
<script>
(() => {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  const state = { cases: [], labels: {}, index: 0, token };
  const el = (id) => document.getElementById(id);
  function api(path, options = {}) {
    const headers = Object.assign({"X-Review-Token": state.token}, options.headers || {});
    return fetch(path, Object.assign({}, options, {headers})).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || body.error || `HTTP ${response.status}`);
      return body;
    });
  }
  function notice(message, error = false) { el("notice").textContent = message; el("notice").className = `notice${error ? " error" : ""}`; }
  function render() {
    const item = state.cases[state.index];
    const label = state.labels[item.id] || {};
    el("case-id").textContent = `${item.id} · ${state.index + 1} / ${state.cases.length}`;
    el("language").textContent = item.language;
    el("task").textContent = item.task;
    el("translation-wrap").hidden = !item.translation;
    el("translation").textContent = item.translation || "";
    el("category").value = label.category || "other";
    el("specialist").value = label.expectedSpecialist || "synthesis";
    el("error-cost").value = String(label.errorCost || 2);
    el("previous").disabled = state.index === 0;
    el("next").disabled = state.index === state.cases.length - 1;
    el("progress").textContent = `${Object.keys(state.labels).length} / ${state.cases.length} 已标注`;
  }
  function move(delta) { state.index = Math.max(0, Math.min(state.cases.length - 1, state.index + delta)); render(); }
  el("previous").addEventListener("click", () => move(-1));
  el("next").addEventListener("click", () => move(1));
  el("save").addEventListener("click", async () => {
    const item = state.cases[state.index];
    try {
      const body = await api("/api/annotation", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({id: item.id, category: el("category").value, expectedSpecialist: el("specialist").value, errorCost: Number(el("error-cost").value)})});
      state.labels[item.id] = body.label;
      render();
      notice(body.finalized ? "全部标注完成，正式标注文件已生成。" : "已保存到本地 draft。", false);
    } catch (error) { notice(error.message, true); }
  });
  if (!state.token) { notice("缺少临时审核令牌，请使用命令输出的本地链接。", true); return; }
  api("/api/session").then((body) => { state.cases = body.cases; state.labels = body.labels; render(); }).catch((error) => notice(error.message, true));
})();
</script>
</body>
</html>'''


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ReviewState:
    def __init__(
        self,
        candidates_path: Path,
        output_path: Path,
        reviewer_id: str,
        minimum_cases: int,
        translations_path: Path | None = None,
    ) -> None:
        _require_private_path(candidates_path)
        _require_private_path(output_path)
        if candidates_path.resolve() == output_path.resolve():
            raise ValueError("Annotation output must not overwrite the candidate dataset.")
        self.candidates_path = candidates_path
        self.output_path = output_path
        self.draft_path = output_path.with_suffix(output_path.suffix + ".draft")
        _require_private_path(self.draft_path)
        self.reviewer_id = reviewer_id
        if not ID_PATTERN.fullmatch(reviewer_id):
            raise ValueError("reviewer-id must be a safe pseudonymous identifier.")
        self.candidate_sha256 = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
        self.cases = load_candidates(candidates_path, minimum_cases)
        self.case_ids = {case["id"] for case in self.cases}
        self.translations = self._load_translations(translations_path)
        self.labels: dict[str, dict[str, Any]] = {}
        self.finalized = False
        self.lock = threading.Lock()
        source = self.output_path if self.output_path.is_file() else self.draft_path
        if source.is_file():
            parsed = load_annotations(source, self.case_ids, self.candidate_sha256)
            if parsed["reviewerId"] != reviewer_id:
                raise ValueError("Existing annotation file belongs to another reviewer.")
            self.labels = parsed["labels"]
            self.finalized = source == self.output_path

    def _load_translations(self, path: Path | None) -> dict[str, str]:
        if path is None:
            return {}
        _require_private_path(path)
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Translation file must exist and be at most 2 MiB.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Translation file must be valid UTF-8 JSON.") from error
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "kind",
            "candidateSha256",
            "language",
            "translations",
        }:
            raise ValueError("Translation file does not match the schema.")
        if (
            value["schemaVersion"] != 1
            or value["kind"] != "secure-agent-workbench/blind-routing-translations"
            or value["candidateSha256"] != self.candidate_sha256
            or value["language"] != "zh-CN"
            or not isinstance(value["translations"], list)
        ):
            raise ValueError("Translation file metadata does not match the candidate dataset.")
        translations: dict[str, str] = {}
        for item in value["translations"]:
            if not isinstance(item, dict) or set(item) != {"id", "text"}:
                raise ValueError("Translation entry does not match the schema.")
            case_id = item["id"]
            text = item["text"]
            if case_id not in self.case_ids or case_id in translations:
                raise ValueError("Translation entry has an unknown or duplicate id.")
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError("Translation entry has invalid text.")
            translations[case_id] = text
        return translations

    def session(self) -> dict[str, Any]:
        return {
            "reviewerId": self.reviewer_id,
            "cases": [
                {
                    "id": c["id"],
                    "language": c["language"],
                    "task": c["task"],
                    **(
                        {"translation": self.translations[c["id"]]}
                        if c["id"] in self.translations
                        else {}
                    ),
                }
                for c in self.cases
            ],
            "labels": self.labels,
            "finalized": self.finalized,
        }

    def save(self, label: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.finalized:
                raise ValueError("Annotation file is already finalized.")
            case_id = label["id"]
            if case_id not in self.case_ids:
                raise ValueError("Unknown candidate id.")
            self.labels[case_id] = label
            complete = set(self.labels) == self.case_ids
            payload = {
                "schemaVersion": 1,
                "kind": REVIEW_KIND,
                "candidateSha256": self.candidate_sha256,
                "reviewerId": self.reviewer_id,
                "labels": [
                    self.labels[c["id"]]
                    for c in self.cases
                    if c["id"] in self.labels
                ],
            }
            _atomic_json(self.output_path if complete else self.draft_path, payload)
            if complete:
                self.finalized = True
                self.draft_path.unlink(missing_ok=True)
            return {"label": label, "completed": len(self.labels), "total": len(self.cases), "finalized": self.finalized}


class ReviewServer(ThreadingHTTPServer):
    state: ReviewState
    token: str


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("referrer-policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("x-review-token", ""), self.server.token)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.send_header("x-frame-options", "DENY")
            self.send_header("referrer-policy", "no-referrer")
            self.send_header("content-security-policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/session":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            self._json(HTTPStatus.OK, self.server.state.session())
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/annotation":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("annotation request body is too large or missing")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {"id", "category", "expectedSpecialist", "errorCost"}:
                raise ValueError("annotation must contain exactly id, category, expectedSpecialist and errorCost")
            if not isinstance(value["id"], str) or value["category"] not in CATEGORIES or value["expectedSpecialist"] not in SPECIALISTS:
                raise ValueError("annotation contains an invalid id, category or specialist")
            if not isinstance(value["errorCost"], int) or isinstance(value["errorCost"], bool) or not 1 <= value["errorCost"] <= 5:
                raise ValueError("errorCost must be an integer from 1 to 5")
            self._json(HTTPStatus.OK, self.server.state.save(value))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": type(error).__name__, "message": str(error)})


def create_review_server(state: ReviewState, host: str, port: int) -> ReviewServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The review server may only bind to loopback.")
    server = ReviewServer((host, port), ReviewHandler)
    server.state = state
    server.token = secrets.token_urlsafe(24)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a private loopback routing annotation workbench.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--minimum-cases", type=int, default=20)
    parser.add_argument("--translations", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    state = ReviewState(
        args.candidates,
        args.output,
        args.reviewer_id,
        args.minimum_cases,
        args.translations,
    )
    server = create_review_server(state, args.host, args.port)
    host, port = server.server_address[:2]
    print(json.dumps({"status": "ready", "host": host, "port": port, "reviewerId": args.reviewer_id, "url": f"http://{host}:{port}/#token={server.token}"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
