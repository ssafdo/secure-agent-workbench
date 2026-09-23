# 私有自然任务路由盲测

## 目的与边界

公开的 50 条中英路由集用于开发期调参与回归，不能证明自然用户分布上的效果。本流程用于在不提交任务正文的前提下，冻结一批经人工审核的自然任务和当前路由实现，再生成不回显正文的本地评估结果。

仓库当前不包含真实用户任务。`benchmarks/private/`、`artifacts/private/` 已被 Git 忽略，私有数据不得上传 NiceEval、CI、Issue、日志或聊天。自动敏感信息扫描只是辅助门禁，不能替代数据所有者授权、人工去敏和组织的数据保留规则。

## 数据准备

由不参与路由规则调整的审核者创建 `benchmarks/private/natural-routing.jsonl`。每行必须符合 `benchmarks/blind_routing_dataset.schema.json`，并包含：

- 不可反推身份的随机 `id`，不要使用用户 ID、工单号或会话 ID。
- `language`、任务类别、人工标注的 `expectedSpecialist` 和 `1..5` 错误成本。
- 已去除姓名、邮箱、电话、密钥、账户、组织内部路径和独特业务标识的 `task`。
- 只有人工复核完成后，才能将 `deidentified` 与 `reviewedByHuman` 设为 `true`。

建议至少 20 条，并单独保存原始数据到受控系统；不要把原始任务放进此仓库。脚本限制数据集为 2 MiB、单行为 16 KiB、单任务为 2000 字符，并拦截一组常见敏感模式，但仍可能漏报或误报。

## 两阶段运行

审核者在路由实现冻结后先封存：

```powershell
$env:PYTHONPATH = "src"
python scripts/blind_routing_eval.py seal `
  --dataset benchmarks/private/natural-routing.jsonl `
  --manifest artifacts/private/blind-routing-manifest.json
```

manifest 只记录数据集和 `src/agent_workbench/supervisor.py` 的 SHA-256、用例数、语言分布与标签分布。封存后再由实现者评估：

```powershell
$env:PYTHONPATH = "src"
python scripts/blind_routing_eval.py evaluate `
  --dataset benchmarks/private/natural-routing.jsonl `
  --manifest artifacts/private/blind-routing-manifest.json `
  --output artifacts/private/blind-routing-result.json
```

默认门禁为准确率至少 `0.8`、加权错误率至多 `0.2`。可用 `--minimum-accuracy` 和 `--maximum-weighted-error-rate` 调整为 `[0,1]` 内的预注册阈值，不能在看到结果后为了通过而修改阈值。

评估会拒绝数据集哈希、路由源码哈希、数量或分布与 manifest 不一致的输入。修改路由后必须让独立审核者重新封存新一轮数据；不要改写旧 manifest 来绕过检查。

## 结果解释

结果包含准确率、错误成本加权率、混淆矩阵、语言切片及匿名逐条预测，不包含 `task`。即使如此，匿名 ID、标签和切片也可能是敏感元数据，因此结果仍只保存在 `artifacts/private/`。

一批盲测只能说明该批样本上的路由表现。它不能替代专业 Agent 的端到端任务成功率、引用正确率、安全门禁或线上影子评估。若门禁失败，先按语言、类别和高错误成本案例归因，再决定扩充确定性规则、增加保守回退，或单独评估本地/托管分类器；不得直接把盲测样本追加到公开回归集后声称问题已解决。
