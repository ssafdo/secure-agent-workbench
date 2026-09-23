# 架构说明

## 参考图如何转化为项目设计

四张参考图包含三个有价值的核心思想：共享入口、专业 Agent 专线、三层隔离。本项目保留这些思想，但分阶段验证，不把“画在图上”当作“已经实现”。

| 参考设计 | Phase 1 落地 | 后续实现 |
|---|---|---|
| Open WebUI 总台 | CLI 适配器 | Open WebUI pipe / webhook bridge |
| 专业 Agent | ResearchAgent | 文档、表格、PPT、旅行等独立 Agent |
| 每项目工作区 | 独立目录 + HMAC 项目 ID + 路径守卫 | 服务端附件桥、对象存储 |
| 执行容器隔离 | 尚未实现 | 每任务容器、只读镜像、资源限额 |
| 网络与密钥隔离 | 网络/执行权限默认禁用 | 出站代理、短期凭证、独立密钥转发服务 |
| Agent trace | JSONL append-only 事件 | OpenTelemetry + 集中日志 |

## 当前组件

- `WorkspaceManager`：生成项目 ID、创建项目布局、校验受控路径、提供项目锁。
- `ToolRegistry`：保存工具元数据并拒绝重复注册。
- `AgentRuntime`：执行权限判断、步数预算、错误处理和 trace。
- `TraceStore`：每会话一个 JSONL 文件，便于回放。
- `ResearchAgent`：显式规划、读取资料、生成汇总、请求写入。
- `modeling`：定义厂商无关的模型消息、结构化响应、工具调用与用量预算协议。
- `ReActAgent`：驱动模型/工具循环；工具执行仍委托 `AgentRuntime`，不能绕过权限。
- `ConversationHistory`：用确定性估算控制上下文大小；摘要旧消息，按 JSON 结构裁剪超大工具结果并保留头尾。
- `ReflectionPolicy`：协议错误或普通工具失败最多纠错一次；权限拒绝、模型预算和工具步数预算不触发 Reflection。
- `SessionStore`：在项目内部持久化有界历史，通过 `expectedVersion` 做乐观并发控制，并在 TTL 到期后删除状态。
- `OfflineResearchModel`：不访问网络的 FakeLLM，用于验证与未来托管模型相同的协议边界。
- `OpenAIResponsesProvider`：Responses API 协议适配层，不拥有工作区或工具执行权限。
- `ResilientModelProvider`：提供瞬态重试和进程内熔断；HTTP 传输层强制请求超时。
- `HostedResearchAgent`：要求托管模型通过受控工具生成固定报告，再验证产物存在。
- `cli`：命令行入口和 loopback HTTP 服务启动器。
- `web`：由同一 HTTP 服务提供的静态工作台；只调用同源 API，不接触模型密钥。
- `ContainerExecutor`：可选的 Docker CLI 适配层；要求摘要锁定镜像和 argv 白名单，并以无网络、只读、非 root、资源受限配置运行。
- `search_text`：固定读取当前项目 `inputs` 的本地检索工具；分块、排序并返回行号引用与风险信号。
- `RetrievalResearchAgent`：只消费 `search_text` 的结构化结果，重新核对源文后生成有引用的报告或无依据拒答。
- `mcp_client`：使用官方 SDK 发现 stdio 工具，经本地策略 admission 后注册为同步 Runtime handler。
- `ResearchSupervisor`：无工具的意图路由层；选择 Synthesis 或 Retrieval 专家，但不创建新的权限或步骤预算。

## 信任边界

```text
trusted CLI user
      |
      v
application process (current trust boundary)
      |
      +-- policy checks -- project workspace
      |
      +-- trace store

NOT YET ISOLATED: Python process, operating-system user, network, CPU/memory
```

离线 ReAct 并不扩大网络边界：FakeLLM 只返回结构化动作，不拥有文件句柄；模型请求的未知工具、越权路径和未批准写入都由 `AgentRuntime` 转换成可观察的失败或拒绝。hosted Provider 同样只能实现 `ModelProvider`，不能直接接触工作区。它会扩大数据出站边界，因此默认关闭，只能由服务端环境启用。

上下文压缩是应用层、厂商无关的确定性机制。system 指令与最近消息优先保留；工具调用和对应结果按原子批次保留。若最近单条工具输出本身超预算，只裁剪输出值并保留 JSON 包装、状态、错误字段以及文本头尾。trace 只记录压缩前后估算值、消息数量和失败类型，不记录摘要、原始提示词或工具输出。托管模型未来可在 Provider 层增加服务端 compaction，但不能替代本地预算与权限检查。

会话请求以 HMAC 项目 ID 隔离，成功完成 Agent 后才原子替换历史文件。单进程项目锁保证同一项目串行执行，乐观版本避免陈旧客户端覆盖新状态。该锁尚不覆盖多进程或多节点；会话正文是功能状态而非 trace，会持久化用户任务和 Agent 回复，目前没有静态加密。真实部署前需要数据库事务、租户鉴权、加密密钥管理和集中式过期任务。

`Path.resolve()` 与 `Path.relative_to()` 负责目录边界校验。它能阻止常见的绝对路径、`..` 和已有符号链接逃逸，但不能代替操作系统沙盒；校验后到使用前仍可能存在 TOCTOU 风险。因此未来 executor 必须进入独立容器，并在容器内再次做相同校验。

浏览器工作台与 `/v1/research` 同源，静态响应包含 CSP、`nosniff`、拒绝 frame 嵌入和无 referrer 策略。报告内容始终通过 `textContent` 渲染，模型返回的 Markdown 不作为 HTML 执行。停止等待只中断浏览器请求，不承诺取消已经开始的服务端模型调用。

Phase 7 的附件桥只处理 UTF-8 文本：浏览器读取用户选择的 `.md/.txt` 内容后复用既有 JSON `sources` 契约，服务端只接收安全项目相对路径并再次检查单份 200 KB 限额。浏览器不传递本地绝对路径，服务端也不直接读取用户文件系统。当前没有 MIME 嗅探、病毒扫描或二进制文档解析，因此不能接受不可信的 Office、PDF、压缩包或可执行文件。

Phase 8 的执行器默认不注册，也不会改变 `ProjectContext` 默认只允许读写的策略。只有服务端给出摘要固定的本地镜像和可执行文件白名单后才能构造执行器；实际调用还需要 `execute` 权限与显式批准。容器不使用 Shell 命令字符串，不自动拉取镜像，不联网，并且只看见项目三个内容目录。Windows Docker Desktop 使用固定非 root UID/GID；POSIX 主机映射当前非 root UID/GID，使容器只能按宿主运行账户已有权限写入绑定目录，同时明确拒绝 UID 0。该实现仍依赖 Docker daemon 的可信性；`container-doctor` 未就绪时不能声称具备真实容器隔离。

本机验证镜像以 `scratch` 为根，只包含 9 KB 的静态 `agent-runner`。它没有 Shell、解释器、包管理器、CA 证书或网络客户端，只能执行固定的输入到输出冒烟操作。2026-09-23 的真实验证中，doctor 返回 `ready: true`，Runtime 通过非 root 容器读取只读输入并成功写入输出挂载。该证据证明当前执行链可工作，但不等同于 Docker daemon、Windows/WSL 内核或未来任意运行镜像已通过生产安全审计。

Phase 13 的检索链仍完全位于应用进程内，不调用托管模型。`search_text` 先计算英文 token/中文双字 BM25 风格分数；若服务端成功加载校验和固定的本地 model2vec 模型，再批量计算 query/chunk 向量并进行混合重排。模型只在服务启动时从本地路径加载，请求阶段没有 Hub 下载；缺失、篡改或编码失败都显式回退到词法模式。Agent 不信任工具返回的 citation，而是重新读取源文件核对路径、行范围、标签和正文后才写报告。注入模式检测只产生风险信号；它可能漏报或误报，因此不能替代 Runtime 权限、工具白名单、密钥隔离和无宿主 Shell 等强制边界。

Phase 14 的 MCP client 是操作员配置边界，不是任意 server 市场。配置要求现有绝对 executable、非空工具白名单和 READ 权限；发现结果还必须声明只读、非破坏、非开放世界 annotation，并通过严格 schema 与描述风险门禁。远端 description 不进入 ToolSpec，只使用本地安全描述；每次调用在新 stdio 进程中重新发现并核对完整定义指纹，再验证实参。调用最终仍落入 `AgentRuntime`，因此权限、步骤预算、锁和 trace 没有旁路。SDK 只继承运行所需的安全系统环境，项目密钥不会传入 server；超时会关闭 session 并回收子进程。该设计不限制可信 server 自身在宿主账户权限内的行为，也无法在 SDK 解析 JSON 行前限制内存，因此不可信 server 必须另行使用容器/microVM 与 OS 资源配额。

Phase 15 的 Supervisor 位于 Agent 与 Runtime 之间，但自身没有 ToolRegistry 或文件访问能力。它从任务文字提取有限意图信号：跨资料汇总优先进入 Synthesis，证据查证进入 Retrieval，未知任务保守使用 Synthesis。选中的专家拿到原始的同一个 Runtime 对象，因此委派不会重置步骤预算、扩大权限或拆分 trace。路由事件不保存任务文字。当前路由是确定性启发式规则，优点是可解释、零模型成本；它不是通用语义分类器，领域扩展前必须先扩大固定任务集。

Phase 16 为路由决策增加三档置信度和两类竞争信号计数。只有单侧明确命中为 `high`，综合与检索信号同时出现为 `medium`，无信号保守回退为 `low`；置信度是规则覆盖诊断，不是统计校准概率。50 条人工策划的中英领域集独立测量混淆矩阵、语言/类别切片和加权错误成本，原有 6 条用例继续执行真实专家并检查最终报告行为。两类指标不能互相替代，下一步仍需对自然用户任务做盲测或影子标注。

Phase 17 增加本地盲测协议，不把私有自然任务变成仓库 fixture。审核者先对任务去敏、标注并执行 `seal`，manifest 将数据集哈希与当时的 `supervisor.py` 哈希绑定；实现者只能在两者未变化时运行 `evaluate`。输出不含任务正文，私有目录由 Git 忽略，CI 只验证协议的负向路径。该设计减少了开发者看过测试样本后调规则的风险，但不能阻止拥有本机文件权限的人读取数据，也不能证明去敏充分，因此数据授权、独立审核和受控存储仍是流程边界。

Phase 18 将去敏候选任务与类别、路由及错误成本标签分开。两位主审核者读取同一份无标签候选集，各自在不查看对方结果的情况下提交只含匿名 ID 和三类标签的文件。比较器验证 ID 全覆盖，报告三类一致率与路由标签 Cohen's kappa；任何字段分歧都要求第三位不同审核者仲裁。只有一致率门禁通过且没有未解决冲突时，才合成 Phase 17 数据集。比较报告不含任务正文或审核者 ID，但本地文件访问权限仍可关联输入，因此这不是密码学盲化。

Phase 19 的审核工作台是独立的 loopback Python HTTP 服务，不复用研究 API。候选集在启动时读取并通过带一次性令牌的同源 API 返回；令牌放在 URL fragment，不会在 HTTP 请求中发送。每位审核者使用独立假名和输出路径，标签草稿通过临时文件、`fsync` 和原子替换保存；只有所有候选 ID 都有标签时才生成正式文件。正式文件绑定候选集 SHA-256，保护审核结果不被悄悄套用到换过正文的候选集，但它不提供远程认证、密码学盲化或多租户并发。

## 项目目录

```text
runtime/projects/<project-id>/
├── inputs/
├── outputs/
├── work/
└── .agent/
    ├── metadata.json
    ├── traces/<session-id>.jsonl
    └── sessions/<session-id>.json
```
