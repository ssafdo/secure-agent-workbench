# 迭代记录

## Phase 1：安全执行内核（已完成）

- [x] 从参考图片提取共享入口、专业 Agent、工作区/执行/网络三层隔离思想
- [x] 写清用户、范围、信任边界与验收标准
- [x] 创建 HMAC 项目身份、独立目录和会话 trace
- [x] 实现路径守卫、内容目录白名单和 1 MB 文本上限
- [x] 实现读写权限分级、写入批准和工具步数预算
- [x] 实现确定性 ResearchAgent 基线
- [x] 建立安全回归测试与问题台账
- [x] 运行 12 个测试和端到端 demo

## Phase 2：LLM Agent loop（已完成基础闭环）

- [x] 定义模型提供商接口、严格 JSON 响应和工具参数 Schema。
- [x] 实现可完全离线的 FakeLLM 与 ReAct 工具循环。
- [x] 增加模型调用次数、token、费用和循环轮次预算。
- [x] 覆盖格式错误、重复 call ID、未知工具、无限循环、预算越界和未批准写入。
- [x] NiceEval 新增 `research/react`，真实运行 1/1 通过。
- [x] 当前 34 项 Python 工程测试通过；ReAct NiceEval 7 条业务断言通过。
- [x] 接入 OpenAI Responses API compatible function calling，不让供应商格式进入核心域模型。
- [x] 增加 HTTP 调用超时、瞬态错误有限重试和进程内熔断。
- [x] 保留 reasoning items 进行多轮工具调用，未知美元费用显式报告为 `null`。
- [x] NiceEval 增加 `research/hosted`，本地 Responses HTTP 模拟链路 9/9 断言通过。
- [x] 新增独立 `hosted` Experiment，凭据只进入被测 Python 进程且真实 usage 才会上报。
- [ ] 使用受控测试 Key 跑 hosted NiceEval，并建立成功率、token、延迟基线。
- [ ] 将重试/熔断扩展到未来异步工具 executor，验证不会留下失控线程或进程。
- [ ] 扩展到至少 20 个任务案例，对比确定性与模型版本的成功率、成本和延迟。

## Phase 3：会话上下文与受控 Reflection（已完成第一轮）

- [x] 新增厂商无关的 `ConversationHistory`、确定性 token 估算和 8K 默认预算。
- [x] 压缩旧消息时保留最近工具调用批次；超大工具 JSON 保留结构与文本头尾。
- [x] 协议错误和普通工具失败最多 Reflection 一次，trace 只记录脱敏类型和计数。
- [x] 权限拒绝不触发 Reflection；模型调用预算与工具步数预算不能被纠错绕过。
- [x] 新增 `react-recovery` 离线故障注入路径及计数型 `agentDiagnostics`。
- [x] Phase 3 完成时 Python 回归 40 项通过。
- [x] NiceEval `research/context-recovery` 真实本地运行 1/1 通过，固定查询无问题。
- [ ] 增加跨 HTTP 请求的持久会话存储，并定义并发更新与过期策略。
- [ ] 对真实 hosted Provider 验证服务端 compaction，与本地压缩做消融对比。

## Phase 4：持久会话（已完成第一轮）

- [x] API 增加可选 `sessionId` 与 `expectedVersion`，无会话请求保持兼容。
- [x] 项目内部原子保存有界历史，默认 TTL 为 24 小时。
- [x] 陈旧版本返回 409；过期返回 410 并删除状态，可从版本 0 重建。
- [x] 同一项目执行锁覆盖读取、Agent 运行与提交；并发请求只允许一个版本提交。
- [x] 失败请求不推进会话版本；非法会话 ID 和 deterministic 会话请求被拒绝。
- [x] NiceEval adapter 使用 typed session slot 保存后端 ID 和版本。
- [x] NiceEval `research/session` 两轮续接及 `t.newSession()` 隔离为 1/1 通过。
- [x] 当前 Python 完整回归 56 项通过；NiceEval 固定查询返回 `issues: []`。
- [ ] 将会话存储迁移到支持事务和多节点锁的数据库。
- [ ] 增加租户鉴权、静态加密、显式删除和后台过期清理任务。

## Phase 5：DeepSeek Provider（已完成协议与配置接入）

- [x] 根据 DeepSeek 官方文档确认 Responses API、function tools、reasoning 和 usage 兼容范围。
- [x] 新增 `DeepSeekResponsesProvider`，复用既有权限、预算、上下文和可靠性边界。
- [x] DeepSeek Key、模型和 Base URL 使用独立服务端环境变量。
- [x] 新增 Provider 配置与协议模拟测试；不会伪造美元成本。
- [x] 新增独立 NiceEval `deepseek` Experiment，dry-run 精确选择 1 条 hosted 用例。
- [x] 使用用户本机 DeepSeek Key 运行第一条真实评估并固定 Run `c642a27e-f821-4d14-afef-cda5288d0765` 查询。
- [x] 建立首条 DeepSeek 基线：1/1 通过，4 次请求，3945 输入 tokens，1172 输出 tokens，9640 ms；美元成本 unavailable。
- [ ] 扩展 DeepSeek 评测集并与离线/其他 hosted 配置比较 P50/P95、成功率和 token 用量。

## Phase 6：浏览器研究工作台（已完成首版）

- [x] Python 服务同源提供 `/`、`/app.css` 和 `/app.js`，无需单独前端服务。
- [x] 默认连接 DeepSeek hosted 引擎，并提供无网络的离线 ReAct 模式。
- [x] 支持最多 20 份 Markdown/TXT 资料、连续会话版本和显式会话重置。
- [x] 展示报告、产物路径、项目 ID、工具轨迹、模型调用、Token、耗时和上下文诊断。
- [x] 静态响应增加 CSP、`nosniff`、frame 限制和 referrer 限制；报告只按文本渲染。
- [x] 桌面三栏与移动端单栏布局完成浏览器视觉检查；同源离线烟雾请求成功。
- [ ] 增加附件桥、真实用户身份、显式服务端取消和浏览器端 E2E 自动化测试。

## Phase 7：受控文本附件桥（已完成首版）

- [x] 浏览器导入 `.md/.txt`，同名文件更新现有资料，不暴露本地绝对路径。
- [x] 客户端限制最多 20 份、单份 200 KB，服务端重复执行 UTF-8 字节大小校验。
- [x] hosted 模式明确提示资料会发送给 DeepSeek；离线模式明确不访问外部模型。
- [x] 报告可复制或下载为 UTF-8 Markdown；模型文本仍不作为 HTML 执行。
- [x] 从 `file://` 误打开页面时自动转向受支持的 loopback 服务地址。
- [x] 当前 Python 完整回归 57 项通过；移动布局完成浏览器视觉检查。
- [ ] 增加 MIME/内容嗅探、恶意内容扫描、真实用户归属和二进制文档解析沙盒。

## Phase 8：容器隔离执行器（本机真实闭环已完成）

- [x] 新增摘要锁定镜像要求，拒绝普通 tag 与 `latest`。
- [x] 只接受结构化 `argv` 数组，并执行可执行文件白名单检查，不接受 Shell 字符串。
- [x] Docker 命令强制 `--pull never`、无网络、只读根文件系统、删除 capabilities、`no-new-privileges`、非 root 用户和 CPU/内存/PID 上限。
- [x] 只挂载当前项目 `inputs`（只读）、`work` 和 `outputs`；不挂载 `.agent`、Docker socket、数据库或宿主环境密钥。
- [x] 超时后按随机容器名执行 `docker rm -f`；stdout/stderr 有独立大小上限。
- [x] 工具默认不注册；注册后仍需要项目 `execute` 权限和单次显式批准。
- [x] 增加 `container-doctor`，以机器可读 JSON 报告 CLI、daemon、镜像摘要和本地镜像状态。
- [x] 新增 8 项负向/隔离测试；当前 Python 完整回归 65 项通过。
- [x] 已安装 Docker Desktop 4.91.0，Docker daemon 29.8.0 可达。
- [x] Docker Hub 网络不可用时改用 `scratch` + 本地静态汇编 runner，构建过程不下载基础镜像。
- [x] 使用不可变本地镜像 ID `sha256:d13deafc...0fa2` 运行 doctor，全部字段就绪且 `ready: true`。
- [x] 真实 `AgentRuntime -> container_exec -> Docker` 冒烟通过：只读输入 `phase-8-real`，输出产物为 `isolated:phase-8-real`。
- [x] 为静态 runner 生成可归档的 SBOM/构建证明，并增加独立 NiceEval 容器用例（Phase 9 完成）。

## Phase 9：容器评估与供应链证据（已完成首版）

- [x] 新增 `container-smoke` CLI，固定验证 doctor、权限、真实 Docker、只读输入、输出产物、trace 与无残留容器。
- [x] 新增 PowerShell 可复现桥 `scripts/container-smoke.ps1`，自动读取本地不可变镜像 ID，不保存密钥。
- [x] 使用 NiceEval 自定义应用 Adapter 接入真实 Windows/Docker 执行链，不伪装成模型 Agent。
- [x] 独立 Experiment `container` 精确选择 `container/smoke`，1 attempt、单并发、无模型费用。
- [x] 真实 Run `c92f0cc5-8282-472e-bc04-73e56c45cebf` 为 1/1 通过，Attempt `@19JKY2KCGTZFF` 的 11 条断言全部登记。
- [x] 固定 `run.get` 查询返回 `issues: []`；本机 WSL 需显式指定 canonical Record 路径。
- [x] 生成 CycloneDX 1.5 SBOM 与 `agent-workbench.container-build/v1` 构建证明。
- [x] 当前 Python 完整回归 66 项通过。
- [x] 将静态 runner 重建、容器 smoke、NiceEval、固定证据生成与 SBOM 校验接入 GitHub Actions。

## Phase 10：可复现 CI 证据链（本地闭环已完成）

- [x] 新增 `container-evidence.yml`，在 Ubuntu runner 从汇编源码重建静态二进制和 `scratch` 镜像。
- [x] CI 顺序执行 Python 回归、真实容器 smoke、NiceEval JSON/JUnit、receipt 提取、SBOM/构建证明生成与校验。
- [x] Windows 本机通过随机 Bearer token、固定 `/smoke`、无请求正文的短生命周期 HTTP 桥连接 WSL NiceEval；保留 `interop=no`。
- [x] Linux CI Adapter 直接调用本机 Docker/Python，不依赖 PowerShell 或 Windows 桥。
- [x] 新 Run `4e80c6fc-f458-49ad-9d6e-935092f33a60`、Attempt `@11JV1GJA6FX3M` 为 1/1 通过，固定查询返回 `issues: []`。
- [x] 本地证据绑定镜像 ID、runner 源码/二进制/Dockerfile 哈希、11 条断言与 NiceEval Run ID，并通过独立 verifier。
- [x] 当前 Python 完整回归 69 项通过，NiceEval 配置检查通过，Docker 无残留容器。
- [x] 工作流已配置 `actions/attest-build-provenance@v2` 与 `actions/attest-sbom@v2`，仅在非 PR 运行签发。
- [ ] 将当前目录初始化/推送到 GitHub 后运行 workflow，获得首份真实 GitHub OIDC attestation；当前不能声称已经签发。

## Phase 11：GitHub 发布与远端证明（私有仓库能力范围内已完成）

- [x] 初始化 `main` 仓库并创建私有 GitHub 仓库 `ssafdo/secure-agent-workbench`。
- [x] 首次远端 Run `35810011590` 暴露 Linux bind mount UID 不匹配，容器读取成功但输出写入以 exit 11 失败。
- [x] POSIX 执行器改为映射当前非 root UID/GID，Windows 保持固定 `65532:65532`，并新增拒绝 root 用户的回归测试。
- [x] 第二次远端 Run `35810295064` 的构建、70 项测试、容器 smoke、NiceEval、证据校验与上传均通过；远端 NiceEval Run 为 `141ae2b0-c911-4b13-b1de-164a598c8ef3`。
- [x] 确认 GitHub 不支持个人账号私有仓库 Artifact Attestations；workflow 只在公开仓库签发，私有仓库明确报告 notice，不使用 `continue-on-error` 隐藏失败。
- [x] 第三次远端 Run `35810487999` 在 37 秒内完成全部可用门禁；远端 NiceEval Run `4242e5dc-6e39-443e-ba98-46228306a5b2` 为 1/1 通过。
- [x] `container-evidence` artifact ID `10729492603` 已上传，归档摘要为 `sha256:cc55093b9d4bbfe13a3ba1c3d6b3af88847b3da89db1cfc4a4a2ae58fb176f34`。
- [ ] 若未来允许公开仓库或迁移到支持 attestations 的组织，再执行真实 GitHub OIDC provenance/SBOM 签发。

## 每次迭代固定流程

`问题/假设 -> eval case -> 最小实现 -> 回归测试 -> trace 分析 -> 风险台账 -> 决定保留或回滚`
