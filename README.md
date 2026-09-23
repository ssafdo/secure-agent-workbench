# Secure Agent Workbench

这是一个从参考架构出发、逐步演进的实习项目。目标不是一次性复制 Open WebUI 或部署一堆服务，而是先建立一个能运行、能测试、能解释安全边界的 Agent 平台内核，再逐步接入 LLM、RAG、MCP、Web UI 和容器执行器。

当前版本为 `0.14.0`，完成 Phase 13：在 Phase 12 的词法检索和引用校验上增加可选的本地多语 embedding、混合重排、显式回退状态及固定 Recall@K/MRR 基准。项目已发布到私有 GitHub 仓库，Ubuntu CI 从源码重建容器、执行 Python、检索基准与 NiceEval 门禁，并上传经过校验的证据。默认路径仍不访问网络或执行进程；只有服务端显式配置执行器和权限后，才会注册容器工具。

## 已实现

- 由 `功能 ID + 用户 ID + 对话 ID` 生成稳定且不暴露原始标识的 HMAC 项目 ID
- 每个项目独立目录、会话目录和进程内执行锁
- 拒绝绝对路径、`..` 穿越以及指向工作区外的符号链接
- 工具注册与权限分级：读取自动允许，写入必须显式批准
- 所有成功、失败和拒绝的工具调用写入 JSONL trace
- 一个 Plan-and-Solve 风格的 `ResearchAgent`，将工作区文本汇总为报告
- 与模型厂商无关的严格 JSON 响应协议、工具 Schema 和用量预算
- 离线 `ReActAgent`，所有模型工具调用仍经过同一权限与路径执行层
- OpenAI Responses API 兼容 Provider，支持严格 function schema、多工具调用和 reasoning item 续传
- hosted 模型请求超时、瞬态错误有限重试、连续失败熔断和冷却探测
- 会话历史预算、旧消息摘要和超大工具结果的结构化头尾裁剪
- 协议/普通工具失败最多一次 Reflection；权限拒绝和预算失败不重试
- 可选的持久会话、24 小时默认 TTL、原子历史提交以及 HTTP 409/410 并发和过期语义
- DeepSeek Responses API 专用配置、完整历史重放、受控工具调用、重试与熔断
- 同源浏览器工作台：任务与资料编辑、DeepSeek/离线模式、连续会话、报告、工具轨迹和用量诊断
- 文本附件桥：浏览器导入 `.md/.txt`、同名更新、20 份/单份 200 KB 边界和 Markdown 报告下载
- 本地检索引擎：按段落/大小分块、英文词与中文双字检索、BM25 风格排序、`path#Lx-Ly` 引用和逐条源文校验
- 可选 `model2vec==0.9.0` 多语 embedding；模型提交与三个运行文件 SHA-256 固定，普通请求绝不自动下载模型
- 混合检索显式报告 `hybrid`、`lexical` 或 `lexical-fallback`；8 条固定基准比较 Recall@1、Recall@3、MRR、引用正确率和无依据拒答
- 检索报告在没有相关证据时明确拒答；资料中的指令覆盖、密钥外传和命令执行文本只作为风险信号，不触发额外工具
- 硬门控容器执行器：摘要锁定镜像、结构化 argv、可执行文件白名单、无网络、只读根文件系统、非 root 和资源上限
- 容器只挂载当前项目的 `inputs`（只读）、`work` 和 `outputs`；不挂载 `.agent`、Docker socket 或宿主机密钥
- `container-doctor` 以 JSON 报告 Docker CLI、daemon、镜像摘要、镜像本地可用性与执行器就绪状态
- `container-smoke` 通过真实 Runtime/权限/挂载/trace 链运行固定隔离冒烟，并检查没有残留容器
- NiceEval `container/container/smoke` 使用 11 条确定性断言验证真实 Docker 执行，不调用模型、不产生 API 费用
- 生成 CycloneDX SBOM 和包含源文件、二进制、Dockerfile、镜像及 NiceEval 证据哈希的构建证明
- GitHub Actions 可从源码重建静态 runner 与 scratch 镜像，执行测试和 NiceEval，并上传证据；非 PR 运行配置 OIDC provenance/SBOM attestation
- GitHub Actions 独立执行 `research/retrieval` NiceEval 门禁并上传 JSON、JUnit 与 receipt 证据
- 模型格式错误、未知工具、无限循环、预算越界和未批准写入回归测试
- 无模型、无网络即可运行的安全与主流程测试

## 快速开始

```powershell
cd E:\agent\secure_agent_workbench
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m agent_workbench demo
python -m agent_workbench container-doctor
python -m agent_workbench container-smoke
```

`demo` 会创建隔离项目，放入两份示例资料，调用研究 Agent 生成 `outputs/research-report.md`，并打印项目 ID、报告和 trace 位置。

HTTP API 的 `/v1/research` 默认使用确定性基线；请求增加 `"engine": "react"` 时走离线模型协议与 ReAct 工具循环。`"engine": "react-recovery"` 是离线故障注入实验路径：首次调用一个不存在的工具，用来证明一次 Reflection 能恢复且不能绕过 Runtime 策略。FakeLLM 不伪造 token 或费用，因此离线 NiceEval 中的 usage 保持 unavailable；hosted 引擎只采用上游实际返回的 token，美元成本保持 `null`。

请求使用 `"engine": "retrieval"` 时走本地检索，不调用托管模型。它只扫描当前项目的 `inputs/*.md|*.txt`，报告与响应中的 citations 会在写入前重新核对源文件和行号。未配置本地模型时使用词法/中文双字基线；配置成功后组合归一化词法分数与余弦相似度。模型缺失、校验失败或编码异常时返回可见的 `lexical-fallback`，不会静默伪装成混合检索。风险模式匹配只提供诊断，不能替代权限、工具白名单和模型侧注入防护。

### 可选本地混合检索

模型下载是显式的准备步骤；HTTP 请求处理阶段只接受已有本地目录：

```powershell
$env:PYTHONPATH = "src"
python -m pip install -e ".[retrieval]"
python scripts/download_retrieval_model.py --output runtime/models/potion-multilingual-128M-i8
python scripts/benchmark_retrieval.py --model-path runtime/models/potion-multilingual-128M-i8 --require-improvement --output artifacts/retrieval/benchmark.json
$env:AGENT_WORKBENCH_EMBEDDING_MODEL_PATH = "runtime/models/potion-multilingual-128M-i8"
python -m agent_workbench serve --port 8767
```

固定模型为 MIT 许可的 `Tokenade/potion-multilingual-128M-i8-tokenade@ba8c5504...`，是 `minishlab/potion-multilingual-128M` 的 int8 量化版本。当前 8 条基准中，词法与混合检索的 Recall@1/MRR 分别为 `0.571429/0.571429` 和 `1.0/1.0`；这只证明当前固定样例的改进，不代表生产语料上的通用质量。

需要跨请求续接时，为 `react`、`react-recovery` 或 `hosted` 请求增加 `"sessionId"` 和 `"expectedVersion"`。首次版本为 `0`，成功响应会返回 `session.version = 1`；下一次必须传回该版本。陈旧版本返回 HTTP 409，过期会话返回 HTTP 410，客户端随后可用版本 `0` 重新开始。会话正文保存在项目内部 `.agent/sessions/`，因此当前版本不适合在磁盘不可信或多人共享的宿主机上保存敏感内容。

### 可选 hosted 引擎

复制 `.env.example` 中的变量到当前 PowerShell 环境，并填入服务端密钥与明确的模型 ID：

```powershell
$env:AGENT_WORKBENCH_MODEL_API_KEY = "<server-side-key>"
$env:AGENT_WORKBENCH_MODEL = "<model-id>"
$env:AGENT_WORKBENCH_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS = "30"
$env:PYTHONPATH = "src"
python -m agent_workbench serve --port 8765
```

然后向 `/v1/research` 发送 `"engine": "hosted"`。密钥和 Base URL 只能由服务端环境配置，不能由 API 请求指定。Provider 遵循官方 [Function calling](https://developers.openai.com/api/docs/guides/function-calling?api-mode=responses) 流程；兼容服务必须实现 Responses API，而不只是 Chat Completions。

### DeepSeek

DeepSeek 当前提供无状态的 Responses API，项目会在每次请求中重放经过预算控制的完整历史，不使用其不支持的 `previous_response_id`。在 PowerShell 中只设置服务端环境：

```powershell
$env:AGENT_WORKBENCH_MODEL_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "<仅保存在本机环境中的密钥>"
$env:DEEPSEEK_MODEL = "deepseek-flash" # 或 deepseek-v4-pro
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:PYTHONPATH = "src"
python -m agent_workbench serve --port 8767
```

服务启动后访问 `http://127.0.0.1:8767/` 使用研究工作台。页面与 API 同源，不读取或展示服务端 API Key；浏览器只提交任务、资料、执行引擎和可选会话版本。

不要直接双击 `src/agent_workbench/web/index.html`。如果从 `file://` 打开，页面会自动跳转到 `http://127.0.0.1:8767/`；服务必须先运行。DeepSeek 模式会把任务与资料内容发送给配置的 DeepSeek API，离线模式不会访问外部模型。

API 请求仍只发送 `"engine": "hosted"`，不能由客户端覆盖模型、Key 或 Base URL。官方接口与模型列表见 [DeepSeek API Docs](https://api-docs.deepseek.com/)；模型可能随服务更新，运行前以官方控制台和文档为准。

查看已有项目：

```powershell
$env:PYTHONPATH = "src"
python -m agent_workbench list-projects
python -m agent_workbench inspect --project-id <project-id>
```

默认运行数据位于 `runtime/`，不会提交到 Git。生产环境必须设置至少 32 个随机字符的 `AGENT_WORKBENCH_SECRET`。

### 可选容器执行器（Phase 8）

容器能力默认完全关闭。先运行诊断：

```powershell
$env:PYTHONPATH = "src"
python -m agent_workbench container-doctor
```

只有 Docker CLI、Docker daemon 和经过审核的本地镜像都准备好后，才设置以下服务端环境变量。镜像必须使用不可变摘要，不能使用 `latest` 或普通 tag：

```powershell
$env:AGENT_WORKBENCH_CONTAINER_ENABLED = "true"
$env:AGENT_WORKBENCH_CONTAINER_IMAGE = "sha256:<本地镜像的64位小写十六进制ID>"
$env:AGENT_WORKBENCH_CONTAINER_EXECUTABLES = "python,node"
python -m agent_workbench container-doctor
```

项目提供了无需联网和基础镜像的最小静态运行镜像：`containers/runner.Dockerfile`。构建后必须读取 Docker 返回的本地 `sha256:...` 镜像 ID，再写入 `AGENT_WORKBENCH_CONTAINER_IMAGE`。远端镜像则使用完整的 `name@sha256:...` 仓库摘要；两者都禁止用普通 tag 代替。

本机离线构建流程：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "as --64 /mnt/e/agent/secure_agent_workbench/containers/agent-runner.s -o /tmp/agent-runner.o && ld -static -o /mnt/e/agent/secure_agent_workbench/containers/agent-runner /tmp/agent-runner.o"
docker build --file containers/runner.Dockerfile --tag secure-agent-runner:dev .
$imageId = docker image inspect --format '{{.Id}}' secure-agent-runner:dev
$env:AGENT_WORKBENCH_CONTAINER_ENABLED = "true"
$env:AGENT_WORKBENCH_CONTAINER_IMAGE = $imageId
$env:AGENT_WORKBENCH_CONTAINER_EXECUTABLES = "agent-runner"
python -m agent_workbench container-doctor
```

`agent-runner` 只实现固定的容器冒烟读写，不包含 Shell、包管理器、网络客户端或动态库。当前真实验证镜像 ID 为 `sha256:d13deafc19928eaac8892b5823839e8807ee52f677db67be9ec5edf216f30fa2`；重新构建后应始终以 Docker 实际返回的新 ID 为准。

Windows 上可用一条命令执行完整冒烟：

```powershell
pwsh -NoProfile -File scripts/container-smoke.ps1
```

当前证据文件位于 `artifacts/container/sbom.cdx.json` 和 `artifacts/container/build-proof.json`。

执行器还使用 `--pull never`，因此运行阶段不会自动下载镜像。即使工具已注册，项目上下文仍默认没有 `execute` 权限，并且每次执行还必须显式批准。当前浏览器研究接口没有向用户开放执行权限。

## NiceEval 评估

NiceEval 集成位于 `niceeval/`，通过真实的 loopback HTTP 服务评估 `ResearchAgent`。NiceEval 0.15.0 的进程协调目前只支持 Linux/macOS；本机 Windows 使用已安装的 `NiceEval-Ubuntu` WSL2 发行版运行：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/baseline --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/react --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/hosted --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && PYTHON=python3 pnpm exec niceeval exp local research/retrieval --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp local research/context-recovery --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp local research/session --rerun all"
python scripts/run_container_niceeval.py
```

第三条命令启动仅监听本机的 Responses 协议模拟器，完整验证 hosted HTTP、function calling、工具策略和报告产物，不访问互联网，也不上报模拟 token。已验证 Run：`43bbf8ac-4dc1-4e4b-ab71-38a546d5e23d`，9/9 断言通过。

第四条命令验证长上下文压缩、超大工具结果裁剪和一次失败恢复。已验证 Run：`4bcba814-fa79-4b30-942f-71e310b6f7dc`，1/1 Attempt 通过；固定查询为 `niceeval/queries/context-recovery-run.json`。

第五条命令验证两轮续接和独立新会话隔离。已验证 Run：`9b79c979-2169-4481-add3-85694c7973fa`，1/1 Attempt 通过；固定查询为 `niceeval/queries/session-run.json`。

Windows 容器命令会启动只存活于本次运行的受限 HTTP 桥：随机 Bearer token、固定 `/smoke` POST、无请求正文，NiceEval 结束即关闭。这样无需放宽当前 WSL 的 `interop=no` 隔离设置；Linux CI 则由 Adapter 直接运行本机 Docker/Python。已验证 Run：`4e80c6fc-f458-49ad-9d6e-935092f33a60`，Attempt `@11JV1GJA6FX3M`，1/1 通过且 11 条断言全部登记；固定查询为 `niceeval/queries/container-run.json`。

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --request queries/container-run.json"
```

真实 DeepSeek 评估使用独立 Experiment：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp deepseek research/hosted --dry"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp deepseek research/hosted --rerun all"
```

第一条只预览，不调用模型；第二条会产生真实 DeepSeek API 用量，只在 WSL 环境已安全配置 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL` 后运行。

已验证真实 DeepSeek Run：`c642a27e-f821-4d14-afef-cda5288d0765`，`research/hosted` 为 1/1 通过。该基线发生 4 次模型请求，输入 3945 tokens、输出 1172 tokens，评估执行耗时 9640 ms；Provider 未返回美元成本。固定查询为 `niceeval/queries/deepseek-run.json`。

真实 Provider 使用独立 Experiment，只有在 WSL 环境安全设置 `AGENT_WORKBENCH_MODEL_API_KEY` 和 `AGENT_WORKBENCH_MODEL` 后才运行：

```bash
cd /mnt/e/agent/secure_agent_workbench/niceeval
PYTHON=python3 pnpm exec niceeval exp hosted research/hosted --rerun all
```

不要把密钥直接写进命令、仓库或评测输入。通用 `hosted` Experiment 尚未产生真实 Run；DeepSeek 的真实结果使用上面的独立 `deepseek` Experiment，且 Provider 未提供美元费用。

查看最新的 ReAct 结果：

```powershell
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval show --run 1612d548-d462-464e-bb4b-93c7aba31458"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval view --run 1612d548-d462-464e-bb4b-93c7aba31458 --no-open --port 4173"
```

第二条命令是持续运行的本地服务；不要先按 `Ctrl+C`。保持终端开启，然后在 Windows 浏览器访问 `http://127.0.0.1:4173`。WSL 的 localhost 代理提示不影响这个本地转发地址。

完整接入边界和机器查询方式见 `docs/niceeval-integration.md`。

## 核心调用链

```text
CLI / HTTP / future Open WebUI bridge
        |
        v
optional Hosted Provider -> ReActAgent
                            |
                            v
WorkspaceManager -> ProjectContext -> AgentRuntime
                                      |    |
                                      |    +-> TraceStore
                                      v
                                ToolRegistry
                                 |       |
                              read     write + approval
                                 \       /
                              isolated workspace
```

## 项目文档

- `docs/spec.md`：用户、场景、功能与验收标准
- `docs/architecture.md`：当前架构、安全边界和参考图片的取舍
- `docs/knowledge-roadmap.md`：Agent 知识整合路线
- `docs/issues.md`：已发现的问题、风险和验证方式
- `docs/eval-plan.md`：评测数据与指标设计
- `docs/hosted-provider.md`：Responses API、可靠性策略与配置边界
- `docs/progress.md`：每阶段完成项和下一步实施顺序

如果在受限 coding sandbox 中无法创建项目内的 `runtime/`，可将运行数据临时指向系统临时目录：

```powershell
$env:AGENT_WORKBENCH_ROOT = Join-Path $env:TEMP "secure-agent-workbench"
python -m agent_workbench demo
```

## 当前边界

本版本已经实现容器执行器代码和安全回归，但只有在 `container-doctor` 返回 `ready: true` 后才能把它视为可运行的容器隔离。当前研究 API 不授予 `execute` 权限；不要把宿主 Shell 暴露给模型。hosted Provider 仍是单独的数据出站边界，尚无操作系统级出站白名单。持久化数据库、MCP 和更强的 microVM 隔离仍在后续阶段。
