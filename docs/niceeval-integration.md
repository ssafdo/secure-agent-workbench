# NiceEval 接入方案

## 选择

- NiceEval 版本：`0.15.0`
- 工作区：`niceeval/` 独立 pnpm + ESM 项目，不修改 Python 依赖图
- 接入等级：Tier 1
- Judge：首轮不启用；当前环境没有 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`
- 被测对象：真实 `ResearchAgent`，通过项目自己的 HTTP 边界调用，不做进程内 import
- 运行平台：NiceEval 0.15.0 不支持 Windows 进程身份；本机通过 WSL2 `NiceEval-Ubuntu` 运行

## 五条验证链

### 协议

`experiments/local.ts -> agents/workbench.ts -> POST /v1/research -> ResearchAgent -> message/tool events`

请求体：

```json
{
  "task": "研究任务",
  "sources": [{ "path": "source.md", "content": "资料正文" }]
}
```

响应包含报告、隔离项目 ID 和经过脱敏的完整工具生命周期。Adapter 将工具生命周期映射成 NiceEval 的 `operation.started` / `operation.finished`。

### 核心任务

`research/baseline` 的正例要求 Agent 读取资料并写出有固定 Markdown 结构的报告，同时确实调用 `list_files`、`read_text` 和 `write_text`；负例不给任何资料，要求 Agent 明确报告无可读来源且不得伪造读取。`research/react` 使用相同 HTTP 边界验证离线模型协议确实驱动三种工具，并经过批准写入、预算与 trace 控制。

### 配置

本地端口是每次 Experiment 启动后产生的运行坐标，只保存在生命周期对象中，由 Adapter 工厂读取。`local` Experiment 为 hosted Eval 启动本地 Responses 协议模拟器；`hosted` Experiment 只从服务端环境读取真实 Key、模型和 Base URL，评估输入不能覆盖这些配置。

### 生命周期

Experiment `setup` 创建临时工作目录和临时 HMAC 密钥，启动 `python -m agent_workbench serve --port 0`，读取实际端口并检查 `/health`。模拟 hosted 路径还会启动仅监听 `127.0.0.1` 的临时 Responses 服务。`teardown` 终止这些进程/服务，并只清理本次创建的临时目录。

### 真实容器

`container` 使用 NiceEval 自定义应用 Adapter，不走聊天协议。Windows 本机保留 WSL `interop=no`：`scripts/run_container_niceeval.py` 启动带随机 Bearer token 的短生命周期 HTTP 桥，Adapter 只能向固定 `/smoke` 发送无正文 POST，再由 Windows CLI 执行 `AgentRuntime -> container_exec -> Docker`。桥随 NiceEval 退出而关闭。Linux CI 不走桥，由 Adapter 直接调用本机 Python 与 Docker。评估断言 doctor、不可变镜像、退出码、成功信号、输出边界、固定产物、trace 和无残留容器；全程不调用模型。

终止状态同时检查 Node 的 `exitCode` 和 `signalCode`，避免服务被信号正常终止后重复等待已经发生的 `exit` 事件。

## 安全边界

- 服务只监听 `127.0.0.1`。
- 临时密钥只进入被测 Python 进程环境，不写入源码、评测输入或结果。
- API 只接收 `.md` / `.txt`，限制请求体、来源数量与路径。
- NiceEval tool event 只暴露工具名、状态和参数键，不暴露资料正文。

## 运行与审阅

从 PowerShell 强制重跑目标 Eval，不采用历史缓存：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/baseline --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/react --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/hosted --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp local research/retrieval --rerun all"
```

真实 hosted 运行必须在 WSL 环境中预先安全配置 `AGENT_WORKBENCH_MODEL_API_KEY` 与 `AGENT_WORKBENCH_MODEL`，然后执行：

```bash
PYTHON=python3 pnpm exec niceeval exp hosted research/hosted --rerun all
```

真实容器评估：

```powershell
python scripts/run_container_niceeval.py
```

人在终端或浏览器审阅已验证 Run。下面默认查看最新的 ReAct 结果：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval show --run 1612d548-d462-464e-bb4b-93c7aba31458"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval view --run 1612d548-d462-464e-bb4b-93c7aba31458 --no-open --port 4173"
```

`view` 是持续运行的服务。不要在访问页面前按 `Ctrl+C`；保持该 PowerShell 窗口运行，并从 Windows 浏览器访问 `http://127.0.0.1:4173`。出现 localhost 代理未镜像警告不影响 WSL 的 localhost 转发。

机器读取时先发现 operation，再校验并执行固定请求：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query discover"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query explain --request queries/first-run.json"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --request queries/first-run.json"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query explain --request queries/react-run.json"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --request queries/react-run.json"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query explain --request queries/hosted-simulated-run.json"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --request queries/hosted-simulated-run.json"
```

首条完整执行结果：Experiment `local`，Run `cbe4f8b9-4c19-4e52-93bf-c17e807855b5`，`1 passed / 0 failed / 0 errored / 0 reused`。

Phase 2 `0.3.0` ReAct 回归结果：Experiment `local`，Run `1612d548-d462-464e-bb4b-93c7aba31458`，`1 passed / 0 failed / 0 errored / 0 reused`，7 条业务断言通过。固定查询文件为 `queries/react-run.json`。

Phase 4 `0.5.0` 会话回归结果：Experiment `local`，Eval `research/session`，Run `9b79c979-2169-4481-add3-85694c7973fa`，`1 passed / 0 failed / 0 errored / 0 reused`。固定查询文件为 `queries/session-run.json`。

Hosted 模拟结果：Experiment `local`，Run `43bbf8ac-4dc1-4e4b-ab71-38a546d5e23d`，Attempt `@15E8DY6TGNKZP`，`1 passed / 0 failed / 0 errored / 0 reused`，9 条业务断言通过。usage 明确为 unavailable，固定查询文件为 `queries/hosted-simulated-run.json`。

真实容器结果：Experiment `container`，Run `4e80c6fc-f458-49ad-9d6e-935092f33a60`，Attempt `@11JV1GJA6FX3M`，`1 passed / 0 failed / 0 errored / 0 reused`，11 条确定性断言通过。usage 为 not-recorded；固定查询文件为 `queries/container-run.json`。本机查询命令显式加 `--record .niceeval/record.sqlite`。

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --record .niceeval/record.sqlite --request queries/container-run.json"
```

Phase 12 检索结果：Experiment `local`，Run `f6f3f22e-db4d-41bb-98a1-f0ec1e3d5ac1`，Attempt `@1S8AM96JEVCA6`，`1 passed / 0 failed / 0 errored / 0 reused`，8 条确定性断言通过。固定查询为 `queries/retrieval-run.json`：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --record .niceeval/record.sqlite --request queries/retrieval-run.json"
```
