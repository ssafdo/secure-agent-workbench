# 评测计划

## 第一层：确定性工程测试

- 身份：相同三元组得到相同项目 ID，不同用户或会话得到不同 ID。
- 权限：读工具自动执行；写工具无批准时拒绝。
- 文件：绝对路径、父目录穿越、跨项目路径被拒绝。
- 可靠性：超过 step budget 后拒绝继续调用。
- 可观测性：成功、失败、拒绝都写入 trace。
- 模型协议：畸形响应、非对象参数和重复 tool-call ID 被拒绝。
- 循环控制：未知工具可观察，无限工具循环被轮次预算终止。
- 用量控制：provider 上报的 token 或费用超过预算时停止。
- Provider 可靠性：瞬态错误有限重试，永久错误不重试，连续失败后熔断并在冷却后探测。
- Responses 协议：多工具调用、严格 Schema、reasoning item 续传和未知费用保持 null。
- 上下文：长历史压缩到预算内，最近用户/工具事实保留，超大工具 JSON 裁剪后仍可解析。
- Reflection：可恢复失败只纠错一次；权限拒绝、模型调用预算和工具步数预算不可绕过。
- 会话：版本 0 创建、连续请求递增、并发陈旧写入冲突、TTL 过期、失败不提交以及新会话隔离。
- DeepSeek：专用环境配置、固定 Responses Base URL、无状态全历史重放、function tools 和真实 token usage 映射。

## 第二层：Agent 任务评测

接入 LLM 后建立至少 20 条 JSONL case，覆盖正常研究、空资料、矛盾资料、长文档、工具失败、prompt injection、高风险写入和多轮追问。

当前 NiceEval 已建立 `research/baseline`、`research/react` 和 `research/hosted` 三条基线。`local` Experiment 中的 FakeLLM 与 Responses 模拟器不产生真实消费，因此 Adapter 将 usage 声明为 unavailable。独立 `hosted` Experiment 才上报真实 API 返回的 token；API 不返回美元费用，在引入受控价格表前不启用美元成本断言。

Phase 3 新增 `research/context-recovery`：使用 8K 应用层上下文预算、长资料和一次可恢复工具失败，同时断言压缩、结构化裁剪、单次 Reflection、工具恢复和受控产物路径。Run `4bcba814-fa79-4b30-942f-71e310b6f7dc` 为 1/1 通过，固定查询返回 `issues: []`。

Phase 4 新增 `research/session`：两次 `t.send()` 续接同一持久会话，并通过 `t.newSession()` 验证项目和资料不泄漏。Run `9b79c979-2169-4481-add3-85694c7973fa` 为 1/1 通过。

Phase 5 新增 `deepseek` Experiment，精确选择 `research/hosted`。真实 Run `c642a27e-f821-4d14-afef-cda5288d0765` 为 1/1 通过：4 次请求、输入 3945 tokens、输出 1172 tokens、评估执行耗时 9640 ms；固定查询返回闭合结果。DeepSeek 未返回美元成本，因此该字段保持 unavailable。

Phase 10 将自定义应用 Experiment `container` 接入可复现 CI 证据链，精确选择 `container/smoke`。真实 Run `4e80c6fc-f458-49ad-9d6e-935092f33a60` 为 1/1 通过，11 条断言覆盖 doctor、不可变镜像、Runtime 工具结果、真实产物、输出边界、trace 与容器回收。该实验不使用 LLM，因此 usage 明确为 not-recorded。

Phase 12 新增 `research/retrieval`：混入相关证据、无关资料和带指令覆盖/命令执行文本的恶意资料，断言检索只调用一次 `search_text`、报告只写一次、没有额外工具动作、相关内容带稳定行号引用、结构化 citation 通过源文校验且风险信号被登记。Run `f6f3f22e-db4d-41bb-98a1-f0ec1e3d5ac1` 为 1/1 通过，8 条确定性断言全部通过；该实验不调用模型，因此 usage unavailable 是预期限制。

Phase 13 为同一用例增加混合模式断言，并用 8 条 JSON 固定集做词法/混合消融。词法 Recall@1/MRR 为 `0.571429/0.571429`，混合模式为 `1.0/1.0`；引用正确率与无依据拒答准确率均保持 `1.0`。NiceEval Run `96a91b20-50ca-49f1-8f15-442b09412645`、Attempt `@199AHPWDSV6DG` 为 1/1 通过，10 条断言全部通过。

记录字段：`task_id`、`input`、`expected`、`actual`、`passed`、`failure_type`、`steps`、`tool_calls`、`input_tokens`、`output_tokens`、`cost`、`latency_ms`。

## 第三层：消融实验

分别关闭检索重排、上下文压缩、Reflection、模型路由和多 Agent 路由，对比任务成功率、引用正确率、成本和 P95 延迟。机制只有在数据上带来收益才保留。
