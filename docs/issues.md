# 问题与风险台账

| ID | 状态 | 严重度 | 问题 | 当前处理 / 下一步 |
|---|---|---|---|---|
| SEC-001 | Partial | Critical | Python 主进程不是安全沙盒，所有不可信执行必须留在独立容器 | Docker 真实冒烟已通过；execute 仍默认关闭且绝不暴露宿主 Shell，生产加固仍待完成 |
| SEC-002 | Mitigated | High | `../`、绝对路径、符号链接可导致目录逃逸 | 使用 resolve + relative_to；已有负向测试 |
| SEC-003 | Mitigated | High | Agent 未经用户同意写文件 | WRITE 工具要求 `approved=True` |
| SEC-004 | Open | High | 路径校验与文件打开之间存在 TOCTOU | 容器内只挂载项目卷；后续研究基于文件描述符的安全打开 |
| SEC-005 | Partial | High | trace 未来可能包含 prompt 或敏感内容 | 当前只记参数键及结果类型/大小；LLM 接入前增加错误与 prompt 脱敏器 |
| SEC-006 | Mitigated | High | Agent 可能读取或覆盖 `.agent` 内部文件 | 工具仅允许访问 `inputs/outputs/work`，且 Agent 不能写 `inputs` |
| ID-001 | Mitigated | Medium | 直接拼接用户 ID 会泄露身份且可猜目录 | HMAC 生成 32 位项目 ID |
| ID-002 | Open | Medium | 开发默认密钥不适合部署 | CLI 警告；部署检查应拒绝默认密钥 |
| CON-001 | Partial | High | 进程内锁无法覆盖多进程或多节点 | Phase 1 仅支持单进程；后续数据库 advisory lock |
| REL-001 | Partial | Medium | 外部调用可能超时或雪崩 | 模型 HTTP 已有 timeout、有限重试和进程内熔断；未来工具 executor 与分布式状态待实现 |
| COST-001 | Mitigated | Medium | 模型调用可能突破 token/金额预算 | ReAct 已按 provider 实测 usage 执行调用数、token 和金额上限；真实 Provider 接入时复验 |
| FILE-001 | Partial | High | 文本附件已有名称、扩展名、数量、大小和项目路径校验，但尚无恶意内容扫描 | 当前只允许 `.md/.txt` 和单份 200 KB；后续加入内容扫描与真实身份归属 |
| NET-001 | Open | Critical | 真实 Agent 可能外传数据或遭受 SSRF | hosted Provider 仅接受管理员环境中的固定 Base URL，但进程尚无操作系统级出站白名单 |
| EVAL-001 | Partial | Medium | 任务质量案例数量不足 | NiceEval 已覆盖 deterministic、ReAct、hosted、会话恢复、DeepSeek 与真实容器基线；后续扩展到至少 20 条业务案例 |
| MODEL-001 | Mitigated | High | 模型返回畸形 tool call、重复 ID 或未知工具 | 严格解析响应；未知工具进入统一 runtime 失败轨迹；已有负向测试 |
| MODEL-002 | Mitigated | High | 模型循环可能无限运行或消耗失控 | 已限制调用、工具步数、token、金额和轮次，并加入请求超时、有限重试和熔断 |
| COST-002 | Open | Medium | Responses API usage 不直接提供美元费用 | `costUSD` 显式为 null；接入受控价格表前不执行美元预算断言 |
| CTX-001 | Mitigated | High | 长历史或超大工具输出可能超过模型上下文并中断任务 | 8K 确定性预算、旧消息摘要、结构化头尾裁剪；Python 与 NiceEval 均覆盖 |
| CTX-002 | Open | Medium | 压缩摘要是有损的，旧细节可能丢失或改变后续决策 | trace 记录压缩元数据；后续用任务集做压缩开/关消融并评估引用正确率 |
| REF-001 | Mitigated | High | Reflection 可能形成无限重试或借重试绕过权限/预算 | 默认最多一次；拒绝和预算错误不触发；Runtime 每次重新执行完整策略检查 |
| SESSION-001 | Mitigated | Medium | 当前 history 只在单次 ReAct 调用内传入，尚无跨请求持久会话 | 已增加原子文件存储、版本检查、TTL 和多轮 NiceEval；生产数据库待实现 |
| SESSION-002 | Open | High | 会话正文包含任务与 Agent 回复，当前磁盘存储没有静态加密 | 部署前加入租户鉴权、KMS/信封加密、显式删除与保留策略 |
| SESSION-003 | Open | High | 进程内项目锁不能协调多进程或多节点会话更新 | 迁移到数据库事务或分布式锁；当前部署限制为单服务进程 |
| DS-001 | Mitigated | Medium | DeepSeek Responses API 不支持服务端会话和 compaction | 应用层重放有界历史，不发送 `previous_response_id`、`conversation` 或 `context_management` |
| DS-002 | Open | Medium | DeepSeek API 不直接返回美元成本，且模型与价格可能变化 | 只记录真实 token，`costUSD` 保持 null；价格比较使用受控、带版本的外部价格表 |
| DS-003 | Mitigated | Medium | 真实账户、配额、区域网络和模型可用性需要运行证据 | 本机真实 DeepSeek NiceEval Run `c642a27e-f821-4d14-afef-cda5288d0765` 已 1/1 通过 |
| EXEC-001 | Mitigated | Critical | 模型可能通过 Shell 字符串、PATH 或任意二进制扩大执行面 | 只接受 argv 数组与纯文件名白名单；镜像摘要锁定；execute 权限和批准双重门控 |
| EXEC-002 | Partial | High | Docker daemon、镜像供应链或宿主配置错误会削弱容器边界 | 使用 `scratch` 与本地静态 runner；doctor、真实冒烟、SBOM、构建证明与 CI 校验已完成，GitHub OIDC attestation 已配置但待远端首次签发 |
| CI-001 | Partial | Medium | 个人账号私有仓库不支持 GitHub Artifact Attestations，已验证证据包不能等同于 OIDC 签名 | 私有仓库继续上传校验后的证据 artifact 并明确 notice；仓库公开或迁移到支持该功能的组织后才启用 provenance/SBOM attestation |
| RAG-001 | Mitigated | Medium | 词法/中文双字基线对同义表达或跨语言问题可能漏召回 | 可选的校验和固定多语 embedding 与混合重排已接入；8 条固定集 Recall@1/MRR 从 0.571429 提升到 1.0，CI 要求改进且 NiceEval 断言未回退 |
| RAG-004 | Partial | Medium | 当前 8 条检索基准规模小，固定阈值可能不能代表真实长文档与领域语料 | 保留显式模式和回退诊断；后续扩展到至少 50 条分领域语料，报告 Precision@K、延迟与内存并重新校准阈值 |
| RAG-002 | Mitigated | High | 检索结果可能伪造路径、行号或正文，造成不可追溯引用 | 写报告前重新读取项目内源文件，逐条核对路径、行范围、citation 标签和正文；伪造引用有负向测试 |
| RAG-003 | Partial | Critical | 资料中的 Prompt Injection 可能诱导模型泄密或调用高风险工具 | 当前确定性检索引擎不执行资料指令，风险模式只作诊断；权限、工具白名单和无宿主 Shell 仍是安全边界，hosted RAG 需单独攻防评估 |
| EXEC-003 | Mitigated | High | 容器超时后可能残留进程，输出可能耗尽内存 | 随机容器名、超时 `rm -f`、CPU/内存/PID 限制和 stdout/stderr 截断均有测试 |
| MCP-001 | Mitigated | Critical | 恶意工具描述或动态 schema 可能向模型注入指令、扩大参数面 | 远端描述不进入 ToolSpec；严格 schema、显式只读 allowlist、annotation 与调用前定义指纹复验均有负向测试 |
| MCP-002 | Mitigated | High | MCP 参数越权、密钥环境继承或超时 server 可能绕过 Runtime 边界 | 调用前 JSON Schema 验证，SDK 最小环境加 credential-name 拒绝，所有 handler 经过 Runtime，超时清理子进程有测试 |
| MCP-003 | Partial | High | 官方 SDK 在解析完整 stdio JSON 行后才执行应用输出上限，恶意 server 仍可能消耗宿主内存或执行任意代码 | MCP server 必须由操作员信任；当前解析后拒绝超大结果，后续将 server 放入有内存/PID/网络限制的容器或 microVM |
| ROUTE-001 | Partial | Medium | 确定性 Supervisor 对未覆盖措辞、跨语言和复合意图可能误路由 | 汇总信号优先、未知意图低置信回退 Synthesis；50 条人工策划中英集和 6 条端到端消融已通过，但自然任务分布验证前不声称通用能力 |
| ROUTE-002 | Mitigated | High | 专业 Agent 委派可能重置预算或绕过权限与 trace | Supervisor 不拥有工具，两个专家接收同一个 Runtime；共享步骤预算和脱敏 route/tool trace 有负向测试 |
| ROUTE-003 | Partial | Low | 规则置信度可能被误解为统计概率 | 只输出 `high|medium|low` 覆盖诊断和竞争信号计数；文档明确未校准，后续用自然任务盲测校准或改名 |
| ROUTE-004 | Partial | High | 自然任务盲测可能泄露用户内容，或在看过样本后调参造成评估污染 | 私有目录不进 Git/CI，要求人工去敏并封存数据/路由哈希，结果不回显正文；敏感扫描仍可能漏报，真实数据收集必须另行授权和受控保存 |
| ROUTE-005 | Partial | Medium | 单人标签或候选集中的预置类别可能带入主观偏差，遗漏困难案例会虚高路由成绩 | 候选集不含任何评估标签；两位独立审核者完整覆盖 ID 并报告一致率/kappa，所有分歧由不同第三人仲裁；标签指南仍待首批数据验证 |

## 记录规则

新增功能同时回答：它扩大了哪个信任边界、增加了哪类失败、用哪个测试发现回归。状态只能在有代码或测试证据时改为 `Mitigated` 或 `Closed`。
