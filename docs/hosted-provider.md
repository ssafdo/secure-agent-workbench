# Hosted Provider 接入

## 边界

`OpenAIResponsesProvider` 只做协议翻译：工作台消息与工具 Schema 转换成 Responses API 请求，再把 `function_call`、最终文本和 token usage 转回内部模型协议。它不直接执行工具；所有工具仍由 `ReActAgent -> AgentRuntime` 执行权限、路径、预算和 trace 检查。

`DeepSeekResponsesProvider` 复用同一协议翻译，但使用 DeepSeek 官方无状态 Responses 端点。它不会调用不受支持的 `previous_response_id`、`conversation`、`store` 或服务端 compaction；完整历史由应用层会话与 `ConversationHistory` 重放和压缩。

依据官方 [Function calling](https://developers.openai.com/api/docs/guides/function-calling?api-mode=responses) 文档，当前实现：

- 使用 JSON Schema 声明 function tools，并启用 strict mode。
- 接受零个、一个或多个 function call。
- 将工具结果作为 `function_call_output` 送回模型。
- 保留并续传 reasoning items，避免推理模型的多轮工具调用丢失上下文。
- token 用量采用 API 返回值；API 未返回美元成本，因此 `costUSD` 为 `null`，不伪造为零。

## 可靠性策略

- 单次 HTTP 请求默认超时 30 秒，可由服务端环境调整。
- 仅网络错误、超时、HTTP 408、409、429 和 5xx 重试。
- 默认最多尝试 3 次，退避为 0.25、0.5 秒，上限 2 秒。
- 鉴权、参数和其他永久错误不重试。
- 连续 3 个逻辑调用在重试后仍失败，熔断 30 秒；冷却后仅允许探测调用。
- Provider 错误由 API 返回 502；熔断拒绝返回 503。

熔断器是单进程内状态。多进程或多节点部署需要 Redis/数据库等共享状态，这一项尚未实现。

## 配置

配置只来自服务端环境：

```text
AGENT_WORKBENCH_MODEL_API_KEY
AGENT_WORKBENCH_MODEL
AGENT_WORKBENCH_MODEL_BASE_URL
AGENT_WORKBENCH_MODEL_TIMEOUT_SECONDS
```

DeepSeek 使用独立变量，避免误把 Key 发往错误网关：

```text
AGENT_WORKBENCH_MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY
DEEPSEEK_MODEL
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

API 请求不能覆盖 Key、模型或 Base URL，避免调用者把服务变成任意网络代理。`AGENT_WORKBENCH_MODEL_BASE_URL` 是管理员信任配置；当前进程仍缺少操作系统级出站白名单。

## 验证范围

Python 自动测试使用内存 Provider 和模拟传输验证格式转换、严格 Schema、超时传递、reasoning item 续传、重试、熔断恢复和完整报告写入。NiceEval `local/research/hosted` 进一步通过 loopback HTTP Responses 模拟服务验证完整 Provider 往返，且不把模拟 token 上报为真实 usage。

真实通用模型使用 `hosted/research/hosted`，真实 DeepSeek 使用 `deepseek/research/hosted`。DeepSeek Run `c642a27e-f821-4d14-afef-cda5288d0765` 已完成 1/1 Attempt：4 次模型请求、输入 3945 tokens、输出 1172 tokens、评估执行耗时 9640 ms。Provider 未返回美元成本，因此 `costUSD` 保持 unavailable。固定查询为 `niceeval/queries/deepseek-run.json`。
