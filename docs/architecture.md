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
