"use strict";

if (window.location.protocol === "file:") {
  window.location.replace("http://127.0.0.1:8767/");
}

const MAX_SOURCES = 20;
const MAX_SOURCE_BYTES = 200_000;

const elements = {
  form: document.querySelector("#research-form"),
  task: document.querySelector("#task"),
  taskCount: document.querySelector("#task-count"),
  sourceList: document.querySelector("#source-list"),
  sourceTemplate: document.querySelector("#source-template"),
  sourceCount: document.querySelector("#source-count"),
  addSource: document.querySelector("#add-source"),
  importFiles: document.querySelector("#import-files"),
  fileInput: document.querySelector("#file-input"),
  transferBoundary: document.querySelector("#transfer-boundary"),
  runButton: document.querySelector("#run-button"),
  runLabel: document.querySelector(".run-label"),
  cancelButton: document.querySelector("#cancel-button"),
  sessionToggle: document.querySelector("#session-toggle"),
  sessionDetail: document.querySelector("#session-detail"),
  resetSession: document.querySelector("#reset-session"),
  newSession: document.querySelector("#new-session"),
  engineOptions: [...document.querySelectorAll(".engine-option")],
  notice: document.querySelector("#notice"),
  reportEmpty: document.querySelector("#report-empty"),
  reportLoading: document.querySelector("#report-loading"),
  loadingLabel: document.querySelector("#loading-label"),
  reportResult: document.querySelector("#report-result"),
  reportContent: document.querySelector("#report-content"),
  copyReport: document.querySelector("#copy-report"),
  downloadReport: document.querySelector("#download-report"),
  resultProject: document.querySelector("#result-project"),
  resultArtifact: document.querySelector("#result-artifact"),
  metricCalls: document.querySelector("#metric-calls"),
  metricTokens: document.querySelector("#metric-tokens"),
  metricDuration: document.querySelector("#metric-duration"),
  metricVersion: document.querySelector("#metric-version"),
  actionCount: document.querySelector("#action-count"),
  actionList: document.querySelector("#action-list"),
  diagCompactions: document.querySelector("#diag-compactions"),
  diagTruncated: document.querySelector("#diag-truncated"),
  diagReflections: document.querySelector("#diag-reflections"),
  diagRoute: document.querySelector("#diag-route"),
  serviceDot: document.querySelector("#service-dot"),
  serviceLabel: document.querySelector("#service-label"),
  recentRuns: document.querySelector("#recent-runs"),
  runCount: document.querySelector("#run-count"),
};

const state = {
  engine: "supervisor",
  sessionId: makeSessionId(),
  sessionVersion: 0,
  controller: null,
  recentRuns: [],
  lastReport: "",
};

const initialSource = {
  name: "architecture.md",
  content:
    "当前 Agent 已实现项目路径守卫、工具权限、执行轨迹和持久会话。\n" +
    "不受信任的 Shell 与 MCP 工作负载尚未进入操作系统容器隔离。\n" +
    "所有结论必须来自给定资料，产物只能写入项目 outputs 目录。",
};

function makeSessionId() {
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "") ?? Date.now().toString(36);
  return `web-${random.slice(0, 28)}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function setNotice(message = "", kind = "") {
  elements.notice.textContent = message;
  elements.notice.className = `notice${kind ? ` ${kind}` : ""}`;
  elements.notice.hidden = !message;
}

function setServiceStatus(online) {
  elements.serviceDot.className = `status-dot ${online ? "online" : "offline"}`;
  elements.serviceLabel.textContent = online ? "服务已连接" : "服务不可用";
}

async function checkHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const body = await response.json();
    setServiceStatus(response.ok && body.status === "ok");
  } catch {
    setServiceStatus(false);
  }
}

function updateTaskCount() {
  elements.taskCount.textContent = `${elements.task.value.length} / 10000`;
}

function updateSourceCount() {
  const count = elements.sourceList.querySelectorAll(".source-editor").length;
  elements.sourceCount.textContent = `${count} / ${MAX_SOURCES}`;
  elements.addSource.disabled = count >= MAX_SOURCES;
  elements.importFiles.disabled = count >= MAX_SOURCES;
  elements.sourceList.querySelectorAll(".remove-source").forEach((button) => {
    button.disabled = count <= 1;
  });
}

function addSource(source = { name: "notes.md", content: "" }) {
  if (elements.sourceList.children.length >= MAX_SOURCES) return;
  const fragment = elements.sourceTemplate.content.cloneNode(true);
  const editor = fragment.querySelector(".source-editor");
  const name = fragment.querySelector(".source-name");
  const content = fragment.querySelector(".source-content");
  const remove = fragment.querySelector(".remove-source");

  name.value = source.name;
  content.value = source.content;
  remove.addEventListener("click", () => {
    editor.remove();
    updateSourceCount();
  });
  elements.sourceList.append(fragment);
  updateSourceCount();
}

function findSourceEditor(name) {
  return [...elements.sourceList.querySelectorAll(".source-editor")].find(
    (editor) => editor.querySelector(".source-name").value.trim() === name,
  );
}

async function importSelectedFiles() {
  const files = [...elements.fileInput.files];
  elements.fileInput.value = "";
  if (!files.length) return;

  let imported = 0;
  let updated = 0;
  const rejected = [];
  for (const file of files) {
    if (!/^[^\\/:*?"<>|]+\.(md|txt)$/i.test(file.name)) {
      rejected.push(`${file.name}（仅支持安全的 .md/.txt 文件名）`);
      continue;
    }
    if (file.size > MAX_SOURCE_BYTES) {
      rejected.push(`${file.name}（超过 200 KB）`);
      continue;
    }
    const existing = findSourceEditor(file.name);
    if (!existing && elements.sourceList.children.length >= MAX_SOURCES) {
      rejected.push(`${file.name}（已达到 ${MAX_SOURCES} 份上限）`);
      continue;
    }
    const content = await file.text();
    if (new TextEncoder().encode(content).length > MAX_SOURCE_BYTES) {
      rejected.push(`${file.name}（UTF-8 内容超过 200 KB）`);
      continue;
    }
    if (existing) {
      existing.querySelector(".source-content").value = content;
      updated += 1;
    } else {
      addSource({ name: file.name, content });
      imported += 1;
    }
  }
  updateSourceCount();

  const summary = [`已导入 ${imported} 份资料`];
  if (updated) summary.push(`更新 ${updated} 份同名资料`);
  if (rejected.length) summary.push(`拒绝：${rejected.join("、")}`);
  setNotice(summary.join("；"), rejected.length ? "" : "success");
}

function readSources() {
  const sources = [];
  const names = new Set();
  for (const editor of elements.sourceList.querySelectorAll(".source-editor")) {
    const path = editor.querySelector(".source-name").value.trim();
    const content = editor.querySelector(".source-content").value;
    if (!path || !/^[^\\/:*?\"<>|]+\.(md|txt)$/i.test(path)) {
      throw new Error("资料文件名必须是安全的 .md 或 .txt 文件名。");
    }
    if (names.has(path)) throw new Error(`资料文件名重复：${path}`);
    names.add(path);
    sources.push({ path, content });
  }
  return sources;
}

function selectEngine(engine) {
  state.engine = engine;
  elements.engineOptions.forEach((button) => {
    const active = button.dataset.engine === engine;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  const labels = {
    supervisor: "正在选择专业 Agent",
    hosted: "正在调用 DeepSeek",
    retrieval: "正在检索项目资料",
    react: "正在运行离线 ReAct",
  };
  elements.loadingLabel.textContent = labels[engine] ?? "正在运行研究任务";
  elements.transferBoundary.textContent =
    engine === "hosted"
      ? "DeepSeek 模式会将任务和资料内容发送给配置的 DeepSeek API。"
      : "离线模式不会把任务或资料发送到外部模型服务。";
  elements.transferBoundary.classList.toggle("local", engine !== "hosted");
  const supportsSession = engine === "hosted" || engine === "react";
  if (!supportsSession) elements.sessionToggle.checked = false;
  elements.sessionToggle.disabled = !supportsSession;
  elements.resetSession.disabled = !supportsSession;
  updateSessionDisplay();
}

function updateSessionDisplay() {
  elements.sessionDetail.textContent = elements.sessionToggle.checked
    ? `版本 ${state.sessionVersion} · ${state.sessionId.slice(-8)}`
    : "每次创建独立项目";
  elements.metricVersion.textContent = String(state.sessionVersion);
}

function resetSession(showMessage = true) {
  state.sessionId = makeSessionId();
  state.sessionVersion = 0;
  updateSessionDisplay();
  if (showMessage) setNotice("已创建新的本地会话。", "success");
}

function setRunning(running) {
  elements.runButton.disabled = running;
  elements.addSource.disabled = running || elements.sourceList.children.length >= MAX_SOURCES;
  elements.importFiles.disabled = running || elements.sourceList.children.length >= MAX_SOURCES;
  elements.fileInput.disabled = running;
  elements.engineOptions.forEach((button) => (button.disabled = running));
  const supportsSession = state.engine === "hosted" || state.engine === "react";
  elements.sessionToggle.disabled = running || !supportsSession;
  elements.resetSession.disabled = running || !supportsSession;
  elements.cancelButton.hidden = !running;
  elements.runLabel.textContent = running ? "正在运行" : "运行研究";

  elements.reportEmpty.hidden = running || Boolean(state.lastReport);
  elements.reportLoading.hidden = !running;
  elements.reportResult.hidden = running || !state.lastReport;
}

function resetMetrics() {
  elements.metricCalls.textContent = "—";
  elements.metricTokens.textContent = "—";
  elements.metricDuration.textContent = "—";
  elements.actionCount.textContent = "0";
  elements.actionList.replaceChildren();
  const empty = document.createElement("li");
  empty.className = "trace-empty";
  empty.textContent = "等待 Agent 调用工具";
  elements.actionList.append(empty);
  elements.diagCompactions.textContent = "—";
  elements.diagTruncated.textContent = "—";
  elements.diagReflections.textContent = "—";
  elements.diagRoute.textContent = "—";
}

function renderActions(actions = []) {
  elements.actionList.replaceChildren();
  elements.actionCount.textContent = String(actions.length);
  if (!actions.length) {
    const empty = document.createElement("li");
    empty.className = "trace-empty";
    empty.textContent = "本次运行没有工具调用";
    elements.actionList.append(empty);
    return;
  }

  actions.forEach((action, index) => {
    const item = document.createElement("li");
    item.className = `action-item ${action.status ?? ""}`;

    const marker = document.createElement("span");
    marker.className = "action-index";
    marker.textContent = String(index + 1);

    const body = document.createElement("span");
    body.className = "action-body";
    const name = document.createElement("strong");
    name.textContent = action.name ?? "unknown";
    const keys = document.createElement("span");
    const argumentKeys = action.input?.argumentKeys ?? [];
    keys.textContent = argumentKeys.length ? argumentKeys.join(", ") : "无参数";
    body.append(name, keys);

    const status = document.createElement("span");
    status.className = "action-state";
    status.textContent = action.status === "succeeded" ? "成功" : action.status ?? "未知";
    item.append(marker, body, status);
    elements.actionList.append(item);
  });
}

function renderResult(body, durationMs) {
  const report = body.report ?? {};
  const usage = body.modelUsage;
  const diagnostics = body.agentDiagnostics ?? {};
  const totalTokens = usage ? (usage.inputTokens ?? 0) + (usage.outputTokens ?? 0) : null;

  state.lastReport = report.content ?? "";
  elements.reportContent.textContent = state.lastReport;
  elements.resultProject.textContent = `Project ${String(body.projectId ?? "—").slice(0, 8)}`;
  elements.resultArtifact.textContent = report.artifactPath ?? "—";
  elements.copyReport.disabled = !state.lastReport;
  elements.downloadReport.disabled = !state.lastReport;
  elements.metricCalls.textContent = usage ? formatNumber(usage.calls ?? 0) : "离线";
  elements.metricTokens.textContent = totalTokens === null ? "—" : formatNumber(totalTokens);
  elements.metricDuration.textContent = `${(durationMs / 1000).toFixed(1)}s`;
  elements.diagCompactions.textContent = formatNumber(diagnostics.contextCompactions ?? 0);
  elements.diagTruncated.textContent = formatNumber(diagnostics.truncatedMessages ?? 0);
  elements.diagReflections.textContent = formatNumber(diagnostics.reflections ?? 0);
  elements.diagRoute.textContent = body.routing
    ? `${body.routing.specialist} · ${body.routing.confidence}`
    : "—";
  renderActions(body.actions);

  if (body.session) {
    state.sessionId = body.session.id;
    state.sessionVersion = body.session.version;
    updateSessionDisplay();
  }

  elements.reportEmpty.hidden = true;
  elements.reportLoading.hidden = true;
  elements.reportResult.hidden = false;
  addRecentRun(elements.task.value.trim(), body.engine, durationMs);
}

function addRecentRun(task, engine, durationMs) {
  state.recentRuns.unshift({ task, engine, durationMs, at: new Date() });
  state.recentRuns = state.recentRuns.slice(0, 6);
  elements.recentRuns.replaceChildren();
  elements.runCount.textContent = String(state.recentRuns.length);

  state.recentRuns.forEach((run) => {
    const item = document.createElement("div");
    item.className = "recent-run";
    const title = document.createElement("strong");
    title.textContent = run.task;
    const meta = document.createElement("span");
    const engineLabel = {
      supervisor: "智能路由",
      hosted: "DeepSeek",
      retrieval: "检索",
      react: "离线",
    }[run.engine] ?? run.engine;
    meta.textContent = `${engineLabel} · ${(run.durationMs / 1000).toFixed(1)}s · ${run.at.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    item.append(title, meta);
    elements.recentRuns.append(item);
  });
}

async function runResearch(event) {
  event.preventDefault();
  setNotice();

  let sources;
  try {
    sources = readSources();
  } catch (error) {
    setNotice(error.message, "error");
    return;
  }

  const task = elements.task.value.trim();
  if (!task) {
    setNotice("请先填写研究任务。", "error");
    elements.task.focus();
    return;
  }

  const payload = { engine: state.engine, task, sources };
  if (elements.sessionToggle.checked) {
    payload.sessionId = state.sessionId;
    payload.expectedVersion = state.sessionVersion;
  }

  resetMetrics();
  setRunning(true);
  state.controller = new AbortController();
  const startedAt = performance.now();

  try {
    const response = await fetch("/v1/research", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.controller.signal,
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.message || `请求失败（HTTP ${response.status}）`);
      error.code = body.error;
      throw error;
    }
    renderResult(body, performance.now() - startedAt);
    setNotice("研究任务已完成，报告与工具轨迹已更新。", "success");
  } catch (error) {
    if (error.name === "AbortError") {
      setNotice("已停止等待。服务端任务可能仍会完成，请勿立即重复提交。", "");
    } else {
      if (error.code === "SessionConflict" || error.code === "SessionExpired") {
        resetSession(false);
      }
      setNotice(error.message || "运行失败，请检查服务状态。", "error");
    }
  } finally {
    state.controller = null;
    setRunning(false);
    checkHealth();
  }
}

elements.task.addEventListener("input", updateTaskCount);
elements.addSource.addEventListener("click", () => addSource());
elements.importFiles.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", importSelectedFiles);
elements.form.addEventListener("submit", runResearch);
elements.cancelButton.addEventListener("click", () => state.controller?.abort());
elements.resetSession.addEventListener("click", () => resetSession());
elements.newSession.addEventListener("click", () => resetSession());
elements.sessionToggle.addEventListener("change", updateSessionDisplay);
elements.engineOptions.forEach((button) => {
  button.addEventListener("click", () => selectEngine(button.dataset.engine));
});
elements.copyReport.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(state.lastReport);
    setNotice("报告已复制到剪贴板。", "success");
  } catch {
    setNotice("浏览器未允许剪贴板访问。", "error");
  }
});
elements.downloadReport.addEventListener("click", () => {
  if (!state.lastReport) return;
  const blob = new Blob([state.lastReport], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "research-report.md";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setNotice("报告下载已开始。", "success");
});

addSource(initialSource);
selectEngine("supervisor");
updateTaskCount();
updateSessionDisplay();
checkHealth();
