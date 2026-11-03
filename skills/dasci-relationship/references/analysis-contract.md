# 分析调用与结果契约

运行分析、调整可选参数或读取机器结果时查阅本文件。选择状态与确认见 [selection-workflow.md](selection-workflow.md)，方法与适用限制见 [statistical-guide.md](statistical-guide.md)，面向用户交付见 [report-workflow.md](report-workflow.md)。

## 调用入口与参数

当 `select` 返回 `ready`，展示摘要后用 `analysis_args` 调用本脚本，追加用户要求的输出/统计参数。完整参数可直接通过以下 CLI 表达：

命令模板：
```text
<python> <skill_dir>/scripts/data_relationship.py analyze \
  --input "<file>" \
  [--sheet "<sheet>" | --sheet-index N] \
  --col1 "<col1>" --col2 "<col2>" \
  --out "<workspace>/dasci-relationship-output/<可读名字>"
```

可选参数：
- `--alpha 0.05`：显著性水平，默认 0.05。
- `--permutations 2000`：小样本秩检验及稀疏表的置换次数；按请求次数执行，不截减或增加。`0` 禁用置换，需要校准的方法仅描述。
- `--no-chart`：不生成图表，但结果和报告保留坐标计划。
- `--plot-x auto|col1|col2`：独立指定绘图横轴，另一字段为纵轴；默认按图形与类型解析。不会交换统计输入。经 select 确认后使用其 analysis_args，不在调用时另改坐标轴。
- `--out BASE`：指定输出父目录；本次成功产物在其中独立的 `run-<run_id>/` 目录。以返回的 `out_dir` 和报告路径为准，不拼接 `BASE/report.html`。
- `--col1-index N` / `--col2-index N`：列名重复或含特殊字符时使用。
- `--col1-type TYPE` / `--col2-type TYPE`：`auto`（默认）、`numeric`、`boolean`、`categorical`、`ordinal`、`datetime`。根据用户确认的业务定义覆盖推断，不自行把低基数测量值改成分类。
- `--col1-order JSON` / `--col2-order JSON`：显式 ordinal 的完整顺序，如 `'["低","中","高"]'`；必须覆盖所有非缺失观察值，允许本样本未出现的合法水平，拒绝漏项和重复项。其他类型不能传顺序。

例如部门用数字 10/20/30 编码时，确认后给该列增加 `--col2-type categorical`；两个水平的无序分类会编码为 boolean。常见真假标签按否=0、是=1；其他显式二分类按首次出现顺序编码。原标签和编码方向见 `levels` / `value_labels`，不可仅看符号解释业务方向。

- `--methods auto`：默认按矩阵执行适用候选；也可传逗号分隔的方法标识，例如 `--methods spearman,kendall_tau_b`。重复项去重，未知或类型不兼容的项会报错并给适用清单。候选因样本条件不满足时保留状态和原因，不偷偷换方法。
- `--seed 20241102`：小样本秩检验及稀疏列联表置换种子，默认 20241102。请求次数原样执行、记录实际次数；每次请求固定种子可复现。

有序统计按用户顺序计算 Spearman/Kendall，或分组秩检验；不把等级解释为等距测量。用户指定方法子集时只执行该子集，所有结果直接来自同一多方法引擎。

当前已交付类型、多方法计算、小样本校准和请求级 Holm 校正。`inference_status=adjusted` 时按各问题的校正证据解释；没有有效 p 时为 `descriptive_only`，不能把 null p 换成近似数值。结果采用统一多方法契约；同一次运行默认生成固定模板 HTML 与同源 Markdown，无需格式开关。

## 结果字段与解释

等待命令退出码为 0，且 stdout 返回 `ok=true`、`publication.status=complete` 后读取结果；`result.json` 保存同一对象。命令仍在运行时不能凭某个 HTML 已存在宣称完成，也不要重跑一个尚未结束的任务。按以下字段读取：

| 字段 | 用途 |
|---|---|
| `col1/col2`、`n/total_rows/missing_pairs`、`cleaning` | 所选字段语义、共同样本和行排除计数 |
| `method_plan`、`methods[]` | 预定候选、实际适用状态、问题与条件，及 test/effect 引用 |
| `tests[]`、`effects[]` | 各叶子统计量、原始/校正 p、校准方式、效应定义与单项区间 |
| `multiplicity`、`inference_status` | 请求级 Holm 检验族；adjusted 或 descriptive_only |
| `conclusions[]`、`comparisons[]` | 分问题证据与限制，以及方法方向/证据差异 |
| `descriptives`、`transformations` | 分组/频数、编码、有序映射及日期转换 |
| `assumptions`、`warnings` | 研究设计假设和数据/推断限制 |
| `report_html_path`、`report_md_path` | HTML 主阅读入口与 Markdown 保存入口 |
| `plot`、`figures[].axes` | 主图计划与逐图真实轴：字段槽位、物理编号、完整名称及日历派生特征；与选择摘要对应 |
| `chart_paths[]`、`figures[]` | 实际成功图像路径及逐图方法映射、状态/原因 |
| `report_template`、`result_path`、`out_dir` | 固定模板 id/version、完整 JSON 与产物目录 |
| `publication.status`、`publication.run_id` | 完整发布状态与本次运行标识；与 HTML 的 data-report-id 及运行目录对应 |

失败时：
```json
{"ok": false, "error": "……", "needs_sheet": true, "sheets": [...]}
```
- `needs_sheet: true`：回到第 1 步，列 sheet 让用户选。
- 其他 `error`：用中文解释，必要时让用户改列/改文件；不要只把 JSON 贴给用户。
- 如果 `warnings` 里有“样本量小”“期望频数低”“Pearson 与 Spearman 差异大”等，必须在最终回复里保留这些限制。
- `col1/col2` 增加 `inferred_kind/effective_kind/type_source/levels/unit`，用于追溯推断、用户覆盖及编码；日期单位 `day` 对应自 epoch 起的天数。`conversion_failures` 记录失败单元格，`source_missing` 是去全空行后的原缺失单元格数；`unique` 保留原列概况，`paired_unique` 记录共同配对后的有效类别数。
- `cleaning` 记录 `original_rows/empty_rows/conversion_failure_rows/missing_pair_rows/n`，后三种排除原因互斥，原始行数减去三类排除等于 N；`columns[].failed_cells` 是各列失败单元格数，两列同一行失败不能重复扣行。
- `method_plan` 固定候选与请求；`methods[]` 的 `ok/descriptive_only/not_applicable`、原因和引用指向 `tests[]/effects[]`。检验保留原假设、统计量、自由度、原始 p 及校准方式；效应保留定义、编码方向和可用的单项区间。逐项读取全部方法和状态，不挑选单一显著结果。
- `multiplicity` 记录一次请求的 Holm family、有效 test_ids、m 和 alpha，包含所有有效叶子 p（含相关检验和日历特征），null p 不计入；效应量和容器不计为额外检验。`tests[].p_adjusted/reject_adjusted/family_id` 指向该校正，原始 p 保留。只有校正 p<alpha 才拒绝对应原假设；等于或大于 alpha 为证据不足。
- `conclusions[]` 按问题逐项引用检验、效应和限制；mixed_evidence 表示同问题的各项校正决定不同，不表示多数决结果。`comparisons[]` 引用方法/检验/有符号效应，记录比较依据、方向及证据差异；差异的可能影响不等于已确定原因。所有方法的 p 自身仍需满足假设；多个相关结果不构成独立重复验证。
- 无可计算推断时 `inference_status=descriptive_only`，各方法仍保留状态和原因。`descriptives` 保留分组/频数，`transformations` 保留日期单位、时区处理、有序和二分类映射。效应区间仍为单项区间，不提供跨方法同时覆盖保证。

## 输出文件

默认输出父目录：`./data-relationship-output/<列名组合>/`；`--out BASE` 可指定父目录。每次运行先在 `.pending-*` 临时目录生成全部文件，通过核验后以一次目录重命名发布到 `run-<run_id>/`。失败不发布本次报告，不覆盖之前的成功结果；旧版遗留文件也不代表本次完成。始终使用本次成功结果返回的路径。

| 文件 | 内容 |
|---|---|
| `report.html` | 默认阅读入口，固定版本模板；CSS/成功图像内嵌，单文件离线可读 |
| `report.md` | 同源完整保存版，图像使用相对路径；与资源目录一起保存 |
| `charts/*.png` | 按问题命名的配套图像，多种方法可共享；全部实际成功图像见 chart_paths |
| `contingency.csv` | 分类分析的完整观测频数（当前分析有列联表时） |
| `expected_counts.csv` | 对应列联表的完整期望频数 |
| `group_summary.csv` | 分组描述统计（适用的两组/多组比较） |
| `datetime_features.csv` | 日历特征筛选明细（仅日期×分类） |
| `result.json` | 机器可读的完整结果 |

图像禁用或预期绘图依赖/字体失败时，两份正文保留全部统计与逐图原因，不留坏引用。HTML 单文件不包含 CSV；完整复查请分享整个目录。任何必需报告写入失败都不能宣称成功。详见 [报告交付与分享边界](report-workflow.md)。

## 常见错误与处理

| 情况 | 处理 |
|---|---|
| 文件找不到 | 确认路径；如果 DSH 沙箱拒绝读取，请用户把文件放到工作区，或申请相应访问权限。不要反复重试同一个被拒绝的路径。 |
| Excel 没给 sheet | 回到第 1 步，列出全部 sheet 让用户选。 |
| sheet 名不存在 | 列出 `available_sheets`，让用户重选；注意大小写和空格。 |
| `.xls` 读取失败 | 让用户另存为 `.xlsx`；不要擅自安装 `xlrd`。 |
| 列名找不到 | 用 `inspect` 的 `index` 改传 `--col1-index` / `--col2-index`；不要把列名猜成别的。 |
| 选到 ID/常量/空列 | 疑似 ID 先确认业务语义，确认为测量值后可显式覆盖；常量/空列须改选，不静默换列。 |
| 选到高基数文本 | 解释直接分析的限制，先按业务规则分组/编码后重新检查，或改选字段。 |
| 样本量太少 | 按各方法状态解释不适用/仅描述及校准原因；候选清单保留。不要下强结论。 |
| 卡方期望频数太低 | 卡方/G 分别置换校准或只作描述；2×2 的适用计划可另列 Fisher。按各结果的 `p_method/status` 解释。 |
| 两列数值但关系非线性 | 对照 Pearson、Spearman、Kendall 与散点图；零相关不能排除非单调依赖，不擅自改成多项式回归。 |

## 质量检查清单

在给出最终回复前，逐条确认：

- [ ] 文件路径和 sheet 是用户明确选择的。
- [ ] 已展示所选字段及类型，目录候选可分页/搜索访问；用户明确选了两列（或确认了组合摘要）。
- [ ] 两列不同，且有效类型不是 ID/常量/空列/高基数文本；覆盖疑似 ID 时有用户确认及来源记录。
- [ ] 方法符合矩阵或用户明确子集；全部候选的结果、状态和限制均可见。
- [ ] 报告里有 N、统计量、df（如适用）、原始/Holm p、效应量、单项 CI（如适用）及检验族大小；结论逐项可追溯。
- [ ] 解释没有把“显著”说成“强”，没有把“不显著”说成“无关”，没有说“导致”。
- [ ] 至少写了一条限制或假设。
- [ ] 摘要、主图和逐图说明的横纵轴一致；显式方向优先，派生图按自己的轴解读，未将换轴解释为统计输入或因果角色变化。
- [ ] 命令已成功退出，publication.status=complete，运行标识和必需产物对应；必要核验和清理完成后才给 HTML/Markdown 入口。无图原因已说明，配套图与CSV归入附件。
