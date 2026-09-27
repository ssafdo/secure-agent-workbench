# 评估汇总

## 结论

项目保留原有 8 条检索 smoke benchmark 和 6 条 Supervisor 功能消融，用于快速回归；对外说明效果时，优先使用规模更大、难度更高的公开挑战集。新挑战集由项目作者构造并公开冻结，不是真实用户数据，也不是第三方独立盲测。

## 公开检索挑战集 v1

- 数据：40 条问题、20 份共享文档；30 条有依据问题和 10 条无依据问题，中英文各 20 条。
- 难点：同义改写、跨语言、语义相近干扰文档、多证据覆盖和无依据拒答。
- 数据 SHA-256：`fd7861ce5eaf3bf028b282f67f00be0a3623a7e9aec9da51c8a6c1611eab5453`。
- 结果文件：`artifacts/retrieval/challenge-v1.json`。

| 指标 | 词法检索 | Hybrid RAG |
|---|---:|---:|
| Recall@1 | 0.350 | 0.350 |
| Recall@3 | 0.567 | 0.750 |
| MRR | 0.511 | 0.619 |
| 全部必要证据进入 Top-3 | 0.533 | 0.700 |
| 无依据拒答准确率 | 0.600 | 0.000 |
| 综合通过率 | 0.550 | 0.525 |

Hybrid RAG 提高了 Top-3 召回和排序质量，但当前语义阈值在共享语料上过于宽松，10 条无依据问题全部返回了证据。该回归没有从结果中删除；在完成阈值校准和新的冻结复验前，不能声称 Hybrid RAG 全面优于词法方案。

运行命令：

```powershell
$env:PYTHONPATH = "src"
python scripts/benchmark_retrieval.py `
  --dataset benchmarks/retrieval_challenge_v1.json `
  --model-path runtime/models/potion-multilingual-128M-i8 `
  --minimum-cases 40 `
  --output artifacts/retrieval/challenge-v1.json
```

## 拒答校准实验与 held-out 复验

为避免在公开检索挑战 v1 上直接调参，项目另建了 24 条软件交付领域开发集，只用于比较 2 个 SHA-256 固定的多语 Model2Vec 模型和 `0.00-0.80` 的接受阈值。预注册目标为：有依据题“全部必要证据进入 Top-3”不低于 `0.70`，在此约束下最大化该指标与无依据拒答准确率的均值。

开发集选择了 `cnmoro/multilingual-e5-small-distilled-16m@813d48d...` 和阈值 `0.00`：全部证据 Top-3 覆盖率 `0.750`、无依据拒答 `0.375`、综合通过率 `0.625`。单纯提高阈值无法同时维持证据覆盖和拒答，说明旧的最终分数不具备稳定的全局可校准性。

选择完成后才创建并冻结主题不同的客户政策测试集：32 条问题、16 份共享文档，24 条有依据、8 条无依据；SHA-256 为 `e292881b96acf742f88c71346e823a6222fbd39fb067ceab49a099efab796fdd`。首次且唯一一次复验结果如下：

| 指标 | 词法检索 | 开发集选中的 E5 Hybrid |
|---|---:|---:|
| Recall@1 | 0.333 | 0.417 |
| Recall@3 | 0.417 | 0.563 |
| MRR | 0.431 | 0.606 |
| 全部必要证据进入 Top-3 | 0.375 | 0.458 |
| 无依据拒答准确率 | 0.250 | 0.000 |
| 综合通过数 | 11/32 | 11/32 |

候选模型提高了召回和排序，但没有提高综合通过数，且拒答仍为 `0/8`。因此该候选未通过发布门禁，生产默认模型保持不变；held-out v2 从此只用于诊断，不再参与参数选择。结果文件为 `artifacts/retrieval/holdout-v2.json`，校准记录为 `artifacts/retrieval/threshold-calibration-v2.json`。

运行校准命令：

```powershell
$env:PYTHONPATH = "src"
python scripts/calibrate_retrieval_threshold.py `
  --dataset benchmarks/retrieval_threshold_dev_v1.json `
  --model-path runtime/models/potion-multilingual-128M-i8 `
  --model-path runtime/models/multilingual-e5-small-distilled-16m `
  --output artifacts/retrieval/threshold-calibration-v2.json
```

## 独立相关性验证器与 held-out v3

项目随后增加与向量召回器独立的多语 cross-encoder 验证层。模型固定为 Apache-2.0 的 `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1@1427fd65...`，使用 SHA-256 固定的 int8 ONNX 权重；普通请求只允许加载本地文件，不自动联网下载。验证器异常、输出数量不符或分数非法时失败关闭，不会静默退回宽松召回。

阈值只在全新 48 对开发集上选择：正负各 24、中英各 24，数据 SHA-256 为 `8d56a6e0954db09081cf7a43151ef38dde9435641bc3a9325ab17d3bdb771056`。预先固定的选择规则要求正例召回至少 `0.85`，随后最大化正负类别中较低的召回率。选中阈值 `0.38`，开发集为 `47/48`；该数字仅是校准结果，不作为最终效果。

校准完成后才创建并冻结市政服务领域 v3：40 条问题、16 份共享文档，30 条有依据、10 条无依据，中英文各 20；SHA-256 为 `bb1b1a3eddd1a0eb7916e0837bffe01bfbd34e0cede318591933bc11de2afda4`。该数据只运行一次，结果如下：

| 指标 | 词法检索 | E5 Hybrid | E5 + 独立验证器 |
|---|---:|---:|---:|
| Recall@1 | 0.400 | 0.633 | 0.433 |
| Recall@3 | 0.444 | 0.711 | 0.433 |
| MRR | 0.450 | 0.736 | 0.433 |
| 全部必要证据进入 Top-3 | 13/30 | 20/30 | 13/30 |
| 无依据拒答 | 5/10 | 2/10 | 9/10 |
| 综合通过 | 18/40 | 22/40 | 22/40 |

验证器把 E5 的无依据拒答从 `2/10` 提升到 `9/10`，但将证据覆盖从 `20/30` 降到 `13/30`，综合通过数没有提高；6 条多证据问题全部失败，跨语言问题也出现过度过滤。因此该候选仍未通过发布门禁，生产默认保持原 Potion 模型且验证器默认关闭。v3 从此只用于诊断，不再调整模型、阈值或题目。

运行命令：

```powershell
$env:PYTHONPATH = "src"
python -m pip install -e ".[relevance]"
python scripts/download_relevance_model.py --output runtime/models/mmarco-mMiniLMv2-L12-H384-v1
python scripts/calibrate_relevance_verifier.py `
  --dataset benchmarks/relevance_verifier_dev_v1.json `
  --model-path runtime/models/mmarco-mMiniLMv2-L12-H384-v1 `
  --output artifacts/retrieval/relevance-calibration-v1.json
python scripts/benchmark_retrieval.py `
  --dataset benchmarks/retrieval_holdout_v3.json `
  --model-path runtime/models/multilingual-e5-small-distilled-16m `
  --relevance-model-path runtime/models/mmarco-mMiniLMv2-L12-H384-v1 `
  --relevance-threshold 0.38 `
  --minimum-cases 40 `
  --output artifacts/retrieval/holdout-v3.json
```

### 多证据查询分解开发实验

项目随后在全新的 32 条制造业 development-only 数据上评估保守查询分解，数据 SHA-256 为 `69e9a25f0b88397fcd673c89fab5a0b70e03b6876bd8c1c54480b9a2ac1d3fbb`。候选只拆分明确的比较、差异和“分别”措辞，让原子句共同参与向量召回和 cross-encoder 验证，并优先为每个原子句保留不同路径的证据。

预先固定的门禁要求多证据至少增加 4 条、无依据拒答不下降、单证据最多损失 1 条、总通过至少增加 3 条。整句验证与分解验证分别通过 `14/32` 和 `16/32`：多证据从 `0/12` 提升到 `2/12`，单证据保持 `5/8`，无依据保持 `9/12`。候选未通过门禁，因此没有创建或运行 v4 held-out，也没有开启生产默认配置。完整结果为 `artifacts/retrieval/decomposition-development-v1.json`。

下一候选不应继续在这份开发集上微调字符串规则；应建立新的开发集，独立校准原子句分数，或采用直接判断“证据集合是否覆盖全部问题部分”的模型。只有先通过新的开发门禁，才创建 v4 held-out。

### 完整原子覆盖门控开发实验

下一候选使用两份新的、互不复用的开发数据。设施运营原子相关性集包含 48 对查询与段落，正负各 24、中英各 24；SHA-256 为 `415e63c3d0e9268bca6960510bcbcfe6b8b504903f6848fa777e7802cf66a43d`。按预先固定的 `0.001-0.500` 网格与正例召回不低于 `0.85` 的约束，选中原子阈值 `0.072`，校准集为 `48/48`。该满分只用于选阈值，不是最终成绩。

随后在采购与库存领域的 32 条独立集成开发集上，要求每个原子问句都找到超过 `0.072` 且路径不同的证据，否则整题拒答。数据 SHA-256 为 `ffeef91c9f167c0936408151549fa59d4c10d339aa6ff21756d0178c1618c84e`。结果如下：

| 开发指标 | 整句验证 | 完整原子覆盖 |
|---|---:|---:|
| 多证据通过 | 2/12 | 5/12 |
| 单证据通过 | 4/8 | 4/8 |
| 无依据拒答 | 12/12 | 11/12 |
| 综合通过 | 18/32 | 20/32 |

预注册门禁要求多证据至少 `+4`、拒答不下降、单证据最多损失 1 条、总通过至少 `+3`。实际分别为 `+3`、下降 1 条、无损失、`+2`，因此产物中的 `candidateGate.passed` 为 `false`。错误拒答来自一条询问两类退货所用快递公司的无依据比较题：两类退货文档都主题相关，但都没有提供快递公司，说明“每个子问题找到主题相关段落”仍不等于“所问属性获得事实支持”。候选保持默认关闭，没有创建或运行 v4。

运行命令：

```powershell
$env:PYTHONPATH = "src;."
python scripts/calibrate_atomic_relevance.py `
  --dataset benchmarks/atomic_relevance_dev_v1.json `
  --model-path runtime/models/mmarco-mMiniLMv2-L12-H384-v1 `
  --output artifacts/retrieval/atomic-relevance-calibration-v1.json
python scripts/benchmark_retrieval.py `
  --dataset benchmarks/retrieval_coverage_dev_v1.json `
  --model-path runtime/models/multilingual-e5-small-distilled-16m `
  --relevance-model-path runtime/models/mmarco-mMiniLMv2-L12-H384-v1 `
  --relevance-threshold 0.38 `
  --decompose-verification-query `
  --atomic-relevance-threshold 0.072 `
  --require-complete-query-coverage `
  --minimum-cases 32 `
  --output artifacts/retrieval/coverage-development-v1.json
```

下一候选需要验证“所问属性是否被文本明确蕴含”，而不仅是主题相关或子问题覆盖。仍须先通过新的开发门禁，才能创建 v4。

### 属性回答性 NLI 校准实验

Phase 32 没有复用前两份开发集，而是新建 48 对 calibration-only 问题与段落，正负各 24、中英各 24，数据 SHA-256 为 `9f230360db187fde58c081336d717a8c8af4584402277b1a683c2d236229931d`。样例覆盖明确回答、明确否定但仍足以回答、同主题却缺少所问属性，以及中英跨语言正负例。

候选模型为 MIT 许可的 `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli@0a71e92a985b6e1ad1828cf67ce9c459639c1dca`，ONNX 权重与四个配置/分词文件均固定 SHA-256。回答性分数定义为 NLI 的 `1 - neutral_probability`，目的是让肯定与明确否定都可表示“问题能够由段落回答”。按预注册的 `0.001-0.999` 网格与可回答召回不低于 `0.8` 的约束，选中阈值 `0.197`：

| 校准指标 | 结果 |
|---|---:|
| 可回答召回 | 22/24 = 0.916667 |
| 缺属性识别 | 13/24 = 0.541667 |
| 综合正确 | 35/48 = 0.729167 |
| 同主题缺属性识别 | 11/16 = 0.6875 |
| 最低语言平衡准确率 | 0.708333 |

预注册门禁要求最差类别召回和同主题缺属性识别均不低于 `0.75`，实际两项均失败；只有最低语言平衡准确率通过 `0.70` 要求。因此实验按校准层停止，没有继续用同一数据挑模板或模型，没有创建集成开发集或 v4，也没有改变生产默认。该结果不能称为 NLI 已修复属性缺失，只能说明通用 NLI 仍不足以承担当前回答性门控。完整逐题分数和失败列表位于 `artifacts/retrieval/answerability-calibration-v1.json`。

运行命令：

```powershell
$env:PYTHONPATH = "src;."
python scripts/download_answerability_model.py `
  --output runtime/models/multilingual-minilm-nli
python scripts/calibrate_answerability.py `
  --dataset benchmarks/answerability_dev_v1.json `
  --model-path runtime/models/multilingual-minilm-nli `
  --output artifacts/retrieval/answerability-calibration-v1.json
```

下一次实验应使用全新 calibration-only 数据比较专门训练的 answerability 模型或结构化“问题属性 - 证据断言”抽取。选型、模板和阈值确定后，仍需先过新的集成开发门禁，才能创建 v4。

### 抽取式 QA 回答性开发实验

Phase 33 改用直接训练于 SQuAD2 可回答/不可回答任务的抽取式 QA 模型，而不是继续调整通用 NLI。候选固定为 MIT 许可的 `dewdev/mdeberta-v3-base-squad2-onnx@8e70bb4dd7955b69e39e0c7347302e536a4b5f27`，int8 ONNX 和三个配置/分词文件均固定 SHA-256。分数定义为最佳正文跨度与 CLS 空答案 logits 差值的 sigmoid，同时记录抽取答案及其正文字符偏移。

新的 48 对 calibration-only 数据与 Phase 32 不重叠，SHA-256 为 `3b751e7d423e1e250dc65c832a32e18d12c6c47544861122ec82c47a4cb322d3`。预注册阈值网格选中 `0.901`：

| QA 校准指标 | 结果 |
|---|---:|
| 可回答召回 | 21/24 = 0.875 |
| 不可回答识别 | 19/24 = 0.791667 |
| 综合分类 | 40/48 = 0.833333 |
| 正例答案片段命中 | 24/24 = 1.0 |
| 英文平衡准确率 | 0.875 |
| 中文平衡准确率 | 0.791667 |

校准总门禁通过，但明确否定回答只有 `1/4` 超过阈值。项目没有据此发布，而是在另一份 32 条集成开发集上增加“否定回答零损失”硬门禁。集成数据 SHA-256 为 `daba89246b34c9f90241c583fbaf6ff0c43fbe0b7411c738eee2aa2875514a30`：

| 集成开发指标 | 完整原子覆盖 | 再加 QA 门控 |
|---|---:|---:|
| 多证据通过 | 7/12 | 1/12 |
| 单证据通过 | 7/8 | 7/8 |
| 无依据拒答 | 10/12 | 11/12 |
| 综合通过 | 24/32 | 19/32 |

预注册集成门禁要求无依据至少 `+2`、有依据最多损失 1 条、否定回答零损失、综合至少 `+1`。实际为无依据 `+1`、有依据损失 6 条、否定回答损失 1 条、综合 `-5`，四项全部失败。主要原因是逐段 QA 在比较题上会把每个原子问题的正确证据过度过滤，说明单段可回答性不能直接替代证据集合级覆盖判断。候选保持默认关闭，没有创建或运行 v4。

运行命令：

```powershell
$env:PYTHONPATH = "src;."
python scripts/download_qa_answerability_model.py `
  --output runtime/models/mdeberta-v3-base-squad2-onnx
python scripts/calibrate_qa_answerability.py `
  --dataset benchmarks/qa_answerability_dev_v1.json `
  --model-path runtime/models/mdeberta-v3-base-squad2-onnx `
  --output artifacts/retrieval/qa-answerability-calibration-v1.json
python scripts/benchmark_retrieval.py `
  --dataset benchmarks/retrieval_qa_coverage_dev_v1.json `
  --model-path runtime/models/multilingual-e5-small-distilled-16m `
  --relevance-model-path runtime/models/mmarco-mMiniLMv2-L12-H384-v1 `
  --relevance-threshold 0.38 `
  --decompose-verification-query `
  --atomic-relevance-threshold 0.072 `
  --require-complete-query-coverage `
  --answerability-model-path runtime/models/mdeberta-v3-base-squad2-onnx `
  --answerability-threshold 0.901 `
  --minimum-cases 32 `
  --output artifacts/retrieval/qa-answerability-development-v1.json
```

下一候选应直接对“全部候选证据组成的集合是否共同回答每个原子问题”建模，避免将单段 QA 分数作为逐条硬过滤器。仍须使用全新开发数据，并在通过后才能创建 v4。

### 证据集合级 QA 校准实验

Phase 34 新增 `answerability_scope=set`：相关性验证和完整原子覆盖先选择证据，再把保留证据合并为一个上下文，逐个验证原子问题；任一原子问题低于阈值时整组拒答，但不再逐段删除证据。该模式默认关闭，验证异常、非法分数或数量错误均失败关闭，并公开每个原子问题的集合分数。

项目创建了新的 40 条集合 calibration-only 数据，每条含两段证据，正负各 20、中英各 20，与 Phase 33 共享问题数为 0；SHA-256 为 `25c0d8fa04477b83ddea11e399f16ce1d7eab80f5f0b845bb82fcfdf14844e76`。使用同一固定 QA 模型，预注册网格选中阈值 `0.859`：

| 集合校准指标 | 结果 |
|---|---:|
| 可回答召回 | 16/20 = 0.8 |
| 不可回答识别 | 15/20 = 0.75 |
| 综合分类 | 31/40 = 0.775 |
| 正例答案片段命中 | 20/20 = 1.0 |
| 同主题缺属性识别 | 11/16 = 0.6875 |

预注册门禁要求同主题缺属性识别至少 `0.75`，实际未通过；明确否定回答也只有 `2/4`。因此实验在校准层停止，没有创建集合级集成开发集，没有运行 v4，也没有发布候选。结论是：改变门控位置解决了“逐段删除多证据”的机制问题，但没有解决基础 QA 模型从同主题文本中强行抽取答案的问题。

运行命令：

```powershell
$env:PYTHONPATH = "src;."
python scripts/calibrate_qa_answerability.py `
  --dataset benchmarks/qa_evidence_set_dev_v1.json `
  --model-path runtime/models/mdeberta-v3-base-squad2-onnx `
  --output artifacts/retrieval/qa-evidence-set-calibration-v1.json
```

发布版本到此停止扩展检索验证器。后续若继续研究，应使用专门的长上下文集合回答性模型或生成式判别器，并重新建立数据，而不是继续在当前三份已揭示数据上调参。

## Supervisor 工作流挑战集 v1

- 数据：24 条端到端工作流，中英文各 12 条；包含 10 条证据任务、6 条无依据任务和 8 条跨文档综合任务。
- 评分：路由正确、必要证据覆盖、无依据拒答、报告写入和工具轨迹；这是确定性工作流评估，不评价开放式报告的主观写作质量。
- 数据 SHA-256：`ba230cf42b03db86c091d745e9ad55609f0d474942a7dac829ef94c48969d756`。
- 结果文件：`artifacts/supervisor/workflow-challenge-v1.json`。
- NiceEval：Run `b9a9dd86-ac27-48f8-9f15-baef6f965e84`，Attempt `@1DY2PND89DYG2`，`1 passed / 0 failed / 0 errored`；该确定性评估不调用模型，usage 为 not-recorded。

| 指标 | 单 Agent | Supervisor |
|---|---:|---:|
| 通过数 | 8/24 | 19/24 |
| 工作流通过率 | 0.333 | 0.792 |
| 通过率 95% Wilson 区间 | 0.180-0.533 | 0.595-0.908 |
| 平均工具调用 | 6.792 | 3.375 |
| 检索/拒答任务平均引用精度 | 0.375 | 0.453 |

Supervisor 保留 5 个失败：3 个属于必要证据未召回，2 个属于无依据问题未拒答。英文为 11/12，中文为 8/12，说明中文证据检索仍是主要薄弱点；平均引用精度只有 0.453，也表明 Top-5 仍包含较多无关证据。该结果比旧的 6/6 消融更适合描述当前能力，但仍属于作者构造的公开离线挑战集。

运行命令：

```powershell
$env:PYTHONPATH = "src"
$env:AGENT_WORKBENCH_EMBEDDING_MODEL_PATH = "runtime/models/potion-multilingual-128M-i8"
python scripts/benchmark_supervisor.py `
  --dataset benchmarks/supervisor_workflow_challenge_v1.json `
  --minimum-cases 24 `
  --output artifacts/supervisor/workflow-challenge-v1.json

wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm exec niceeval exp supervisor supervisor/workflow-challenge --rerun all"
wsl -d NiceEval-Ubuntu -- bash -lc "cd /mnt/e/agent/secure_agent_workbench/niceeval && pnpm --silent exec niceeval query run --request queries/workflow-challenge-run.json"
```

## 真实 DeepSeek 基线

真实 DeepSeek NiceEval 用例为 1/1 通过，发生 4 次模型请求，输入 3945 tokens、输出 1172 tokens，评估耗时 9640 ms。该结果只证明托管模型端到端链路跑通。Provider 没有返回美元成本，因此 `costUSD` 保持 unavailable。

## 对外表述边界

- 可以说：在公开冻结的离线挑战集上测得上述结果，并保留完整失败列表和数据哈希。
- 不应说：真实用户准确率达到 79.2%，或 Hybrid RAG 已经全面优于词法检索。
- 不应说：E5 模型已经修复无依据拒答；它在开发集改善、在 held-out 测试集没有泛化，因此没有发布。
- 不应说：cross-encoder 已全面修复检索。它在 v3 将无依据拒答提高到 `9/10`，但牺牲了证据覆盖，综合通过仍为 `22/40`，因此同样没有发布。
- 不应说：多语 NLI 已能判断属性蕴含。它在校准集只识别 `13/24` 个缺属性负例，门禁失败后未进入集成评估。
- 不应说：抽取式 QA 的 `40/48` 校准分类或 `24/24` 答案命中代表最终检索质量。它在独立集成开发集使综合通过从 `24/32` 降到 `19/32`，因此没有发布。
- 不应说：集合级 QA 已解决多证据验证。它在新的集合校准集仍未通过同主题缺属性门禁，因此没有进入集成评估。
- 仍待完成：用全新、获授权且人工去敏的自然任务做独立盲测；开放式报告质量还需要明确 rubric 和互不可见的人工复核。
