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
- [x] 已推送私有 GitHub 仓库并完成远端 workflow；个人私有仓库不支持的 OIDC attestation 限制在 Phase 11 明确记录。

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

## Phase 12：本地检索、引用与注入防护（首版完成）

- [x] 新增确定性分块与 BM25 风格词法检索，支持英文 token 和中文双字片段。
- [x] `search_text` 只扫描当前项目 `inputs/*.md|*.txt`，返回最多 10 条带行号的结构化结果。
- [x] 新增 `retrieval` 引擎和浏览器模式；无相关证据时明确拒答，且不允许持久会话。
- [x] 报告写入前逐条验证 path、行范围、citation 标签与源文正文，伪造引用测试会失败。
- [x] 指令覆盖、密钥外传与命令执行模式被标记为风险信号；资料不会引发额外工具调用。
- [x] NiceEval `research/retrieval` Run `f6f3f22e-db4d-41bb-98a1-f0ec1e3d5ac1` 为 1/1 通过，Attempt `@1S8AM96JEVCA6` 的 8 条断言全部通过。
- [x] 当前 Python 完整回归 78 项通过，固定查询返回 `issues: []`，NiceEval 配置检查通过。
- [x] GitHub Actions 增加独立 retrieval NiceEval 门禁与 JSON/JUnit/receipt artifact。
- [x] Phase 13 已引入本地 embedding 与混合重排，并用同义表达、跨语言和矛盾资料数据集衡量 Recall@K、MRR 与引用正确率。

## Phase 13：可选本地 embedding 与混合检索（本地闭环已完成）

- [x] 增加可选依赖 `model2vec==0.9.0`；默认安装仍保持零运行依赖。
- [x] 固定 MIT 多语模型仓库、提交和三个运行文件 SHA-256；普通请求不进行网络下载。
- [x] 将词法归一化分数与余弦相似度组合，显式返回 `lexical`、`hybrid` 或 `lexical-fallback`。
- [x] 模型缺失、校验失败和编码失败均可见回退；相关负向测试覆盖且不会阻断词法检索。
- [x] 新增 8 条固定数据，覆盖精确命中、同义改写、中英跨语言、无关问题、矛盾资料和 Prompt Injection。
- [x] 词法 Recall@1/Recall@3/MRR 为 `0.571429/0.571429/0.571429`；混合模式为 `1.0/1.0/1.0`，两者引用正确率与无依据拒答准确率均为 `1.0`。
- [x] Python 完整回归 `82/82` 通过，`niceeval check` 通过。
- [x] NiceEval Run `96a91b20-50ca-49f1-8f15-442b09412645`、Attempt `@199AHPWDSV6DG` 为 1/1 通过，10 条断言确认混合模式、引用和注入 containment。
- [x] CI 新增固定模型下载/校验、词法与混合基准比较及 benchmark artifact。
- [ ] 将固定集扩展到至少 50 条领域样例，再评估 Precision@K、P95 延迟、内存和阈值稳定性。

## Phase 14：官方 SDK MCP 安全接入（本地闭环已完成）

- [x] 增加可选依赖 `mcp==2.2.0`，默认安装和现有 HTTP 服务不加载 MCP runtime。
- [x] stdio server command 必须是现有绝对文件；工具必须在显式非空 allowlist 中且只允许 READ。
- [x] 强制严格 JSON Schema、实参验证、只读 annotation、本地安全描述和调用前定义指纹复验。
- [x] SDK 默认最小环境不继承 DeepSeek/API 密钥；额外环境拒绝 credential-like 名称。
- [x] 调用有硬超时、JSON 输出上限、错误归一化和子进程清理；Agent 仍只经过统一 Runtime/trace。
- [x] 新增 12 项 MCP 测试；Python 完整回归当前 94 项通过，`niceeval check` 通过。
- [x] NiceEval `mcp/mcp/smoke` Run `d2f75bee-7c98-4dee-a4fb-3d908ada981d`、Attempt `@1KBYF6AT9MVMV` 为 1/1 通过，9 条断言全部通过，固定查询无问题。
- [x] GitHub Actions 增加独立 MCP NiceEval 门禁与 JSON/JUnit/receipt artifact。
- [ ] 将不可信 MCP server 放入独立容器或 microVM，并在协议 JSON 解析前增加传输字节上限。

## Phase 15：Supervisor 与专业 Agent 路由（本地闭环已完成）

- [x] 新增不拥有工具的 `ResearchSupervisor`，只输出枚举化路由决策。
- [x] 证据、引用、查证和问句路由到 Retrieval 专家；全量、对比和跨文档任务路由到 Synthesis 专家；未知意图保守回退 Synthesis。
- [x] 两个专家复用同一个 `AgentRuntime`，步骤预算、项目锁、权限和工具 trace 不因委派重置。
- [x] 新增 `agent_route` trace，只记录 supervisor、专业 Agent、原因码和信号数，不记录任务正文。
- [x] HTTP API 和浏览器增加 `supervisor` 引擎，响应公开路由结果，浏览器默认使用离线智能路由。
- [x] 6 条固定混合集覆盖证据查证、无依据拒答、全量汇总、跨文档比较和保守回退。
- [x] 单 Agent 成功 `3/6`、Supervisor 成功 `6/6`，成功率差 `+0.5`；平均工具调用 `4.167 -> 3.167`。
- [x] NiceEval Run `14e019f8-48ce-47c2-a164-fde9cc3b15ac`、Attempt `@15PGA3882A4C2` 为 1/1 通过，9 条断言全部通过，固定查询无问题。
- [x] Python 完整回归 104 项通过；Supervisor benchmark 可在仓库根目录不设置 `PYTHONPATH` 直接运行。
- [x] 浏览器实测默认智能路由、禁用不适用的连续会话、显示所选专家；桌面和移动视口的四引擎 2x2 布局无重叠或横向溢出。
- [x] GitHub Actions 增加 Supervisor benchmark、NiceEval 门禁与独立 evidence artifact。
- [x] Phase 16 已扩展到 50 条人工策划中英领域路由任务；自然用户任务仍需独立盲测。

## Phase 16：路由可靠性与失败归因（本地实现完成）

- [x] 路由输出增加 `high|medium|low` 置信度及 synthesis/retrieval 竞争信号数；trace 仍不保存任务正文。
- [x] 新增 50 条中英双语策划集，覆盖证据、无依据问题、比较、综合、复合意图、未知意图和对抗 Agent 名称。
- [x] 路由准确率 `50/50`，加权错误 `0`；英文和中文均为 `25/25`，复合意图 `4/4`，未知意图低置信回退 `4/4`。
- [x] 基准输出混淆矩阵、语言/类别切片、置信度分布、逐条结果和错误列表。
- [x] NiceEval 新增独立 `supervisor/routing` 门禁，原 6 条端到端消融继续保留。
- [x] 最新远程 NiceEval Run `95972efb-0202-4794-96a9-3025147cae8d` 为 2/2 通过；消融 Attempt `@1VNXD25FNH1AP`、路由 Attempt `@17196879B4FBE` 共 21 条断言通过。
- [x] Python 完整回归 106 项通过；两个 Supervisor 基准、依赖检查与 NiceEval 配置检查通过。
- [ ] 收集去敏后的自然用户任务做盲测，评估分布外措辞，再决定保留规则或引入本地/托管分类器。

## Phase 17：私有自然任务盲测协议（本地实现完成）

- [x] 新增严格 JSONL schema；每条任务要求匿名 ID、人工标签、错误成本以及显式去敏/人工审核声明。
- [x] `seal` 同时锁定数据集和 Supervisor 路由源码 SHA-256，并记录数量、语言与标签分布。
- [x] `evaluate` 在哈希和分布一致时才运行，输出准确率、加权错误、混淆矩阵、语言切片和匿名逐条结果，不回显任务正文。
- [x] 私有数据集、manifest 和结果均被 Git 忽略；不会接入 NiceEval 或上传 CI。
- [x] 增加敏感模式、数据篡改、路由源码变化、manifest 分布篡改、人工审核声明与阈值范围负向测试。
- [x] Python 完整回归 `114/114`，50 条策划路由集仍为 `50/50`、加权错误 `0`，NiceEval 配置检查通过。
- [ ] 由独立审核者收集一批获得授权且人工去敏的自然任务，在修改路由前预注册阈值并封存；仓库当前没有真实用户任务或自然流量结论。

## Phase 18：独立标注与冲突仲裁（本地实现完成）

- [x] 将只含语言/任务的无标签候选集、两份主审核标注和可选第三人仲裁拆成独立私有文件。
- [x] 强制两位主审核者 ID 不同、标注完整覆盖候选 ID，禁止遗漏困难案例。
- [x] 报告类别、专业 Agent、错误成本一致率和专业 Agent 的 Cohen's kappa，不回显任务正文或审核者 ID。
- [x] 默认三类一致率门禁均为 `0.8`；任何字段冲突都必须由不同的第三人逐条仲裁。
- [x] 只有门禁通过且冲突清零才生成兼容 Phase 17 的最终 JSONL；所有输入输出仍只保存在 Git 忽略目录。
- [x] Python 完整回归 `120/120`，50 条策划路由集仍为 `50/50`、加权错误 `0`，NiceEval 配置检查通过。
- [ ] 招募两位主审核者和一位仲裁者，在获得授权的首批自然任务上验证标签指南；仓库仍不声称已有自然流量结果。

## Phase 19：本地审核工作台（本地实现完成）

- [x] 新增只绑定 `127.0.0.1` 的逐条审核页面，候选任务 API 和保存 API 均要求一次性令牌。
- [x] 页面只显示无标签候选任务；审核者独立选择类别、专业 Agent 和错误成本，不接触模型、NiceEval 或研究 API。
- [x] 草稿使用原子替换保存，服务重启可恢复；全部候选完成后才原子生成正式标注文件并删除 draft。
- [x] 正式标注绑定候选集 SHA-256，候选集变化后旧标注不能被仲裁器复用。
- [x] 新增 4 项审核服务测试，覆盖安全响应头、令牌、草稿、完整化、非法输入和最终冻结。
- [ ] 使用获得授权的首批自然任务和三位真实审核者验证工作流；仓库仍没有真实用户任务或自然流量结论。

## Phase 20：首次自然任务诊断与路由信号分层（开发闭环已完成）

- [x] 从公开许可的 WildChat 发布版筛选 20 条外部自然交互任务；只保留首轮用户正文，人工复核去敏，来源、许可和版本保存在 Git 忽略的私有 provenance 中。
- [x] 两轮不同审核者 ID 的主标注文件使类别/专业 Agent/错误成本一致率达到 `0.85/0.85/1.0`，专业 Agent Cohen's kappa 为 `0.693878`；3 条分歧由第三个 ID 仲裁。工具不验证操作者真实身份，不能据此声称三名独立自然人。
- [x] 冻结数据集和旧路由源码后评估：准确率 `0.6`、加权错误率 `0.4`，未通过预注册的 `0.8/0.2` 门禁；英文与中文准确率均为 `0.6`。
- [x] 旧任务逐条结果已经揭晓，明确降级为私有诊断集；不把任务正文加入公开 fixture，不用修改后的路由重跑旧集宣称提升。
- [x] Supervisor 改为强综合、强检索、弱问句三层信号；概念性差异问题不再因单个 compare/difference 词误判为跨资料综合，长文交付也不再被问号覆盖。
- [x] 新增 50 条不含旧诊断集正文的中英自然措辞开发集；与原 50 条策划集分别达到 `50/50`、加权错误 `0`。
- [x] NiceEval Supervisor Run `a7a8b0ee-f926-469a-b3fe-b33cc407a587` 完成端到端消融、原策划路由集和自然措辞开发集三项评估，`3/3` 通过且无模型 token/费用。
- [ ] 收集第二批全新、未见、获许可且人工去敏的自然任务，重新独立标注、封存并评估 `0.21.0`；在此之前不声称自然任务门禁已经恢复。
