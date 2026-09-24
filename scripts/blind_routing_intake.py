from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.blind_routing_adjudicate import _require_private_path
from scripts.blind_routing_eval import (
    ID_PATTERN,
    MAX_DATASET_BYTES,
    MAX_LINE_BYTES,
    MAX_TASK_CHARACTERS,
    _sensitive_reason,
)
from scripts.blind_routing_review import _atomic_json

DATASET = "allenai/WildChat-1M"
DATASET_REVISION = "7d6490e462285cf85d91eabea0f9a954fbddcd1f"
DATASET_LICENSE = "ODC-BY-1.0"
DATASET_URL = "https://huggingface.co/datasets/allenai/WildChat-1M"
DATASET_API = "https://huggingface.co/api/datasets/allenai/WildChat-1M"
ROWS_API = "https://datasets-server.huggingface.co/rows"
INTAKE_FIELDS = {"id", "language", "task", "sourceRow"}
MAX_BODY_BYTES = 32 * 1024

HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Private intake review</title>
  <style>
    :root { color: #202226; background: #f2f4f6; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; min-height: 100vh; }
    main { width: min(920px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 48px; }
    header { display: flex; justify-content: space-between; gap: 20px; align-items: end; border-bottom: 1px solid #d8dce1; padding-bottom: 18px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .eyebrow { margin: 0 0 8px; color: #1769e0; font-size: 11px; font-weight: 700; }
    .progress { color: #5e6670; font-size: 13px; white-space: nowrap; }
    .panel { margin-top: 24px; padding: 24px; background: #fff; border: 1px solid #d8dce1; border-radius: 8px; box-shadow: 0 8px 24px rgba(24, 33, 45, .06); }
    .meta { display: flex; justify-content: space-between; gap: 16px; color: #69717b; font-size: 12px; }
    textarea { width: 100%; min-height: 230px; margin: 18px 0; padding: 16px; resize: vertical; color: #17191d; background: #f7f8f9; border: 1px solid #d8dce1; border-radius: 6px; font: 14px/1.65 "Segoe UI", "Microsoft YaHei", sans-serif; }
    textarea:focus, button:focus { outline: 3px solid rgba(23, 105, 224, .2); outline-offset: 1px; }
    .decision { display: flex; gap: 22px; padding: 14px 0; border-top: 1px solid #e0e3e7; border-bottom: 1px solid #e0e3e7; }
    label { display: flex; gap: 8px; align-items: center; color: #343a42; font-size: 13px; font-weight: 700; }
    .actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 22px; }
    .actions div { display: flex; gap: 8px; }
    button { min-height: 40px; padding: 0 14px; cursor: pointer; color: #29313a; background: #fff; border: 1px solid #c9ced5; border-radius: 5px; font: inherit; }
    button.primary { color: #fff; background: #1769e0; border-color: #1769e0; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    .notice { min-height: 22px; margin-top: 14px; color: #16794d; font-size: 13px; }
    .notice.error { color: #b63835; }
    @media (max-width: 680px) { header { display: block; } .progress { display: block; margin-top: 10px; } .panel { padding: 18px; } .decision { align-items: flex-start; flex-direction: column; } .actions { align-items: stretch; flex-direction: column; } .actions div { width: 100%; } .actions button { flex: 1; } }
  </style>
</head>
<body>
<main>
  <header><div><p class="eyebrow">PRIVATE DEIDENTIFICATION REVIEW</p><h1>第二批候选任务审核</h1></div><div id="progress" class="progress">连接中</div></header>
  <section class="panel">
    <div class="meta"><span id="case-id">-</span><span id="language">-</span></div>
    <textarea id="task" maxlength="2000" aria-label="去敏后的任务正文"></textarea>
    <div class="decision">
      <label><input type="radio" name="decision" value="approve">批准并确认已去敏</label>
      <label><input type="radio" name="decision" value="exclude">排除这条任务</label>
    </div>
    <div class="actions"><div><button id="previous" type="button">上一条</button><button id="next" type="button">下一条</button></div><button id="save" class="primary" type="button">保存这条</button></div>
    <div id="notice" class="notice" role="status" aria-live="polite"></div>
  </section>
</main>
<script>
(() => {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  const state = { cases: [], reviews: {}, index: 0, token };
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
    const review = state.reviews[item.id];
    el("case-id").textContent = `${item.id} - ${state.index + 1} / ${state.cases.length}`;
    el("language").textContent = item.language;
    el("task").value = review?.task ?? item.task;
    document.querySelectorAll('input[name="decision"]').forEach((input) => { input.checked = input.value === review?.decision; });
    el("previous").disabled = state.index === 0;
    el("next").disabled = state.index === state.cases.length - 1;
    el("progress").textContent = `${Object.keys(state.reviews).length} / ${state.cases.length} 已审核`;
  }
  function move(delta) { state.index = Math.max(0, Math.min(state.cases.length - 1, state.index + delta)); render(); notice(""); }
  el("previous").addEventListener("click", () => move(-1));
  el("next").addEventListener("click", () => move(1));
  el("save").addEventListener("click", async () => {
    const item = state.cases[state.index];
    const decision = document.querySelector('input[name="decision"]:checked')?.value;
    if (!decision) { notice("请选择批准或排除。", true); return; }
    try {
      const body = await api("/api/review", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({id: item.id, decision, task: el("task").value})});
      state.reviews[item.id] = body.review;
      render();
      if (!body.finalized && state.index < state.cases.length - 1) move(1);
      notice(body.finalized ? `审核完成，已生成 ${body.approved} 条正式候选。` : `已保存；当前批准 ${body.approved} 条。`);
    } catch (error) { notice(error.message, true); }
  });
  if (!state.token) { notice("缺少临时审核令牌，请使用命令输出的本地链接。", true); return; }
  api("/api/session").then((body) => { state.cases = body.cases; state.reviews = body.reviews; render(); }).catch((error) => notice(error.message, true));
})();
</script>
</body>
</html>'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "secure-agent-workbench/0.21.0"})
    with urlopen(request, timeout=30) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(f"Dataset service returned HTTP {response.status}.")
        return json.load(response)


def _normalize_task(text: str) -> str:
    return " ".join(text.split()).strip()


def _extract_candidate(row: dict[str, Any], source_row: int) -> tuple[str, str] | None:
    language = {"English": "en", "Chinese": "zh"}.get(row.get("language"))
    if language is None or row.get("toxic") is not False or row.get("redacted") is not False:
        return None
    conversation = row.get("conversation")
    if not isinstance(conversation, list):
        return None
    first_user = next((message for message in conversation if isinstance(message, dict) and message.get("role") == "user"), None)
    if first_user is None or first_user.get("toxic") is True or first_user.get("redacted") is True:
        return None
    content = first_user.get("content")
    if not isinstance(content, str):
        return None
    task = _normalize_task(content)
    if len(task) < 12 or len(task) > MAX_TASK_CHARACTERS or _sensitive_reason(task) is not None:
        return None
    return language, task


def collect_candidates(
    output: Path,
    previous_provenance: Path | None,
    start_offset: int,
    english: int,
    chinese: int,
    fetch_json: Callable[[str], Any] = _fetch_json,
) -> dict[str, Any]:
    _require_private_path(output)
    if output.exists():
        raise ValueError("Intake output already exists; choose a new batch path.")
    metadata = fetch_json(DATASET_API)
    if not isinstance(metadata, dict) or metadata.get("sha") != DATASET_REVISION:
        raise RuntimeError("WildChat repository revision does not match the pinned revision.")
    excluded_rows: set[int] = set()
    if previous_provenance is not None:
        _require_private_path(previous_provenance)
        previous = json.loads(previous_provenance.read_text(encoding="utf-8"))
        for case in previous.get("cases", []):
            if isinstance(case, dict) and isinstance(case.get("sourceRow"), int):
                excluded_rows.add(case["sourceRow"])
    quotas = {"en": english, "zh": chinese}
    selected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    offset = start_offset
    scanned = 0
    while any(sum(item["language"] == language for item in selected) < target for language, target in quotas.items()):
        query = urlencode({"dataset": DATASET, "config": "default", "split": "train", "offset": offset, "length": 100})
        payload = fetch_json(f"{ROWS_API}?{query}")
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Dataset service returned no more rows before quotas were met.")
        for row_offset, wrapped in enumerate(rows):
            source_row = wrapped.get("row_idx") if isinstance(wrapped, dict) else None
            row = wrapped.get("row") if isinstance(wrapped, dict) else None
            if not isinstance(source_row, int):
                source_row = offset + row_offset
            scanned += 1
            if source_row in excluded_rows or not isinstance(row, dict):
                continue
            extracted = _extract_candidate(row, source_row)
            if extracted is None:
                continue
            language, task = extracted
            if sum(item["language"] == language for item in selected) >= quotas[language]:
                continue
            digest = hashlib.sha256(task.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            selected.append({"id": f"b2-{secrets.token_hex(8)}", "language": language, "task": task, "sourceRow": source_row})
        offset += len(rows)
        if scanned > 20_000:
            raise RuntimeError("Candidate scan limit reached before language quotas were met.")
    _atomic_jsonl(output, selected)
    return {
        "status": "collected",
        "output": str(output),
        "cases": len(selected),
        "languages": {language: sum(item["language"] == language for item in selected) for language in quotas},
        "scannedRows": scanned,
        "datasetRevision": DATASET_REVISION,
        "taskTextPrinted": False,
    }


def load_intake(path: Path) -> list[dict[str, Any]]:
    _require_private_path(path)
    if not path.is_file() or path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("Intake file must exist and be at most 2 MiB.")
    values: list[dict[str, Any]] = []
    ids: set[str] = set()
    source_rows: set[int] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"Intake line {line_number} exceeds the limit.")
        value = json.loads(raw_line)
        if not isinstance(value, dict) or set(value) != INTAKE_FIELDS:
            raise ValueError(f"Intake line {line_number} does not match the schema.")
        if not isinstance(value["id"], str) or not ID_PATTERN.fullmatch(value["id"]) or value["id"] in ids:
            raise ValueError(f"Intake line {line_number} has an invalid or duplicate id.")
        if value["language"] not in {"en", "zh"}:
            raise ValueError(f"Intake {value['id']} has an unsupported language.")
        if not isinstance(value["sourceRow"], int) or value["sourceRow"] < 0 or value["sourceRow"] in source_rows:
            raise ValueError(f"Intake {value['id']} has an invalid or duplicate source row.")
        if not isinstance(value["task"], str) or not value["task"].strip() or len(value["task"]) > MAX_TASK_CHARACTERS:
            raise ValueError(f"Intake {value['id']} has invalid task text.")
        ids.add(value["id"])
        source_rows.add(value["sourceRow"])
        values.append(value)
    if not values:
        raise ValueError("Intake file is empty.")
    return values


class IntakeState:
    def __init__(self, intake: Path, output: Path, provenance: Path, minimum_approved: int = 20) -> None:
        for path in (intake, output, provenance):
            _require_private_path(path)
        if len({path.resolve() for path in (intake, output, provenance)}) != 3:
            raise ValueError("Intake, candidate output and provenance paths must be distinct.")
        self.intake_path = intake
        self.output_path = output
        self.provenance_path = provenance
        self.draft_path = output.with_suffix(output.suffix + ".intake-draft")
        _require_private_path(self.draft_path)
        self.minimum_approved = minimum_approved
        self.intake_sha256 = _sha256(intake)
        self.cases = load_intake(intake)
        if minimum_approved < 1 or minimum_approved > len(self.cases):
            raise ValueError("minimum-approved must be positive and cannot exceed the intake size.")
        self.case_ids = {case["id"] for case in self.cases}
        self.reviews: dict[str, dict[str, Any]] = {}
        if output.exists() or provenance.exists():
            if output.is_file() and provenance.is_file():
                raise ValueError("Intake review is already finalized; use a new batch path.")
            raise ValueError("Candidate output and provenance are incomplete; preserve them and investigate before retrying.")
        self.finalized = False
        self.lock = threading.Lock()
        if self.draft_path.is_file():
            value = json.loads(self.draft_path.read_text(encoding="utf-8"))
            if value.get("intakeSha256") != self.intake_sha256 or value.get("kind") != "secure-agent-workbench/blind-routing-intake-review":
                raise ValueError("Intake draft does not match the current intake file.")
            reviews = value.get("reviews")
            if not isinstance(reviews, list):
                raise ValueError("Intake draft has invalid reviews.")
            for review in reviews:
                self._validate_review(review)
                if review["id"] in self.reviews:
                    raise ValueError("Intake draft contains a duplicate review id.")
                self.reviews[review["id"]] = review

    def _validate_review(self, review: Any) -> None:
        if not isinstance(review, dict) or set(review) != {"id", "decision", "task"}:
            raise ValueError("Review must contain exactly id, decision and task.")
        if review["id"] not in self.case_ids or review["decision"] not in {"approve", "exclude"}:
            raise ValueError("Review has an unknown id or decision.")
        task = review["task"]
        if not isinstance(task, str) or len(task) > MAX_TASK_CHARACTERS:
            raise ValueError("Reviewed task text is invalid.")
        if review["decision"] == "approve":
            if not task.strip():
                raise ValueError("Approved task text cannot be empty.")
            reason = _sensitive_reason(task)
            if reason is not None:
                raise ValueError(f"Approved task failed the sensitive-data scan: {reason}.")

    def session(self) -> dict[str, Any]:
        return {
            "cases": [{"id": case["id"], "language": case["language"], "task": case["task"]} for case in self.cases],
            "reviews": self.reviews,
            "finalized": self.finalized,
            "minimumApproved": self.minimum_approved,
        }

    def save(self, review: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.finalized:
                raise ValueError("Intake review is already finalized.")
            review = {**review, "task": _normalize_task(review["task"])}
            self._validate_review(review)
            updated = {**self.reviews, review["id"]: review}
            ordered = [updated[case["id"]] for case in self.cases if case["id"] in updated]
            approved = [item for item in ordered if item["decision"] == "approve"]
            complete = set(updated) == self.case_ids
            if complete and len(approved) < self.minimum_approved:
                raise ValueError(f"At least {self.minimum_approved} approved cases are required; revise exclusions or collect a larger intake.")
            self.reviews = updated
            if complete:
                by_id = {case["id"]: case for case in self.cases}
                candidates = [
                    {"id": item["id"], "language": by_id[item["id"]]["language"], "task": item["task"], "deidentified": True, "reviewedByHuman": True}
                    for item in approved
                ]
                _atomic_jsonl(self.output_path, candidates)
                provenance = {
                    "schemaVersion": 1,
                    "kind": "secure-agent-workbench/natural-routing-provenance",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "status": "approved-for-blind-labeling",
                    "source": {"dataset": DATASET, "datasetUrl": DATASET_URL, "revision": DATASET_REVISION, "license": DATASET_LICENSE},
                    "selection": {"intakeCases": len(self.cases), "approvedCases": len(approved), "excludedCases": len(self.cases) - len(approved), "humanReviewRequired": True, "humanReviewCompleted": True},
                    "intakeSha256": self.intake_sha256,
                    "cases": [{"id": item["id"], "sourceRow": by_id[item["id"]]["sourceRow"], "textModifiedDuringReview": item["task"] != by_id[item["id"]]["task"]} for item in approved],
                    "attestation": {"datasetLicenseVerified": True, "selectedTextHumanReviewed": True, "approvedForBlindEvaluation": True},
                }
                _atomic_json(self.provenance_path, provenance)
                self.draft_path.unlink(missing_ok=True)
                self.finalized = True
            else:
                _atomic_json(self.draft_path, {"schemaVersion": 1, "kind": "secure-agent-workbench/blind-routing-intake-review", "intakeSha256": self.intake_sha256, "reviews": ordered})
            return {"review": review, "completed": len(self.reviews), "approved": len(approved), "total": len(self.cases), "finalized": self.finalized}


class IntakeServer(ThreadingHTTPServer):
    state: IntakeState
    token: str


class IntakeHandler(BaseHTTPRequestHandler):
    server: IntakeServer

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
        if urlsplit(self.path).path != "/api/review":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("Review request body is too large or missing.")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            result = self.server.state.save(value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": type(error).__name__, "message": str(error)})
            return
        self._json(HTTPStatus.OK, result)


def create_server(state: IntakeState, host: str = "127.0.0.1", port: int = 0) -> IntakeServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Intake review may bind only to loopback.")
    server = IntakeServer((host, port), IntakeHandler)
    server.state = state
    server.token = secrets.token_urlsafe(24)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and review a private blind-routing intake batch.")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--previous-provenance", type=Path)
    collect.add_argument("--start-offset", type=int, default=800_000)
    collect.add_argument("--english", type=int, default=22)
    collect.add_argument("--chinese", type=int, default=8)
    review = commands.add_parser("review")
    review.add_argument("--intake", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--provenance", type=Path, required=True)
    review.add_argument("--minimum-approved", type=int, default=20)
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.command == "collect":
        if args.start_offset < 0 or args.english < 1 or args.chinese < 1:
            parser.error("offset must be non-negative and language quotas must be positive")
        print(json.dumps(collect_candidates(args.output, args.previous_provenance, args.start_offset, args.english, args.chinese), ensure_ascii=False, indent=2))
        return 0
    state = IntakeState(args.intake, args.output, args.provenance, args.minimum_approved)
    server = create_server(state, args.host, args.port)
    host, port = server.server_address[:2]
    print(json.dumps({"status": "ready", "host": host, "port": port, "url": f"http://{host}:{port}/#token={server.token}"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
