# Feature：不同类型字段的多方法关系分析

- 标识：`relationship-statistics-coverage`
- 状态：已完成；T1–T4 及取消兼容后的完整 Feature 验收通过，原 T5 已取消。
- 适用对象：通过 `dasci-relationship` 分析 CSV / Excel 两列关系的用户及调用模型。

## Non-Goals

- 不做因果推断、多变量回归、全表自动两两分析、事后组间两两比较。
- 不做文本向量化、自动业务分箱、时序预测或自相关修正；重复测量与有时间依赖的观测不提供有效性保证。
- 不穷举统计方法，不将相关/秩/均值检验包装为能发现任意依赖的通用独立性检验。
- 不改 sheet 交互和 HTML 渲染；它们分别由后续 Feature 验收。
- 保留运行时不依赖 SciPy 的约束，不自动安装依赖。

## 业务意图与现状

让用户按字段的业务语义分析关系；一次请求默认运行一组适用的常见方法，从线性、单调、均值或秩分布等视角说明关系，并对照证据与限制。
本能力并入现有统计 Feature，复用同一字段对、清理结果与结构化输出；不另设独立 Feature。

立项基线脚本已有 Pearson、Spearman 参考、卡方/Fisher/置换、点二列、ANOVA/Kruskal-Wallis 和日期特征筛选。
当时缺口包括：没有 ordinal 类型与类型覆盖入口，数字分类编码被视作连续数值，小样本秩检验仅近似；多方法仅存在于个别分支，缺少统一方法计划、跨方法校正和对照解释。实施进展见文末证据。

最小样本已确认：`低/中/高` 被当作无序分类，`0/1` 和部门数字编码被当作 numeric，`有/无` 中的 `无` 在类型推断前被删除；数值 ID 也可能仅被警告而继续参与分析。

## 核心数据契约

| 对象 | 必需字段及含义 |
|---|---|
| ColumnSpec | `index`：原表 1-based 列位置；`name`：显示列名；`inferred_kind`；`effective_kind`；`type_source: inferred/user`；`levels`：有序水平或二分类编码表；`unit`：如日期转换后的天 |
| AnalysisRequest | 文件、sheet、两个列选择器、两列类型覆盖及水平顺序、`methods: auto/方法标识列表`、`alpha`、`permutations`、`seed` |
| MethodPlan | `candidate_ids`、`available_ids`、`requested`、`effective_kinds`、每项分析问题和适用性条件；在计算 p 前根据语义和样本结构确定，不按显著性增删方法 |
| MethodResult | `id`、`question`、`n`、`status: ok/descriptive_only/not_applicable`、`reason`、`test_ids`、`effect_ids`、`related_method_ids`；不适用候选也保留在清单 |
| TestResult | `id`、`method_id`、可选 `feature`、`null_hypothesis`、`statistic_name/statistic_value`、适用的 `df`、`p_value` 或 null、`p_method`、`family_id`、`p_adjusted` 或 null、`reject_adjusted` 或 null、状态及原因 |
| AnalysisResult | `ok`、文件/sheet 来源、`col1/col2` ColumnSpec、`n/total_rows/missing_pairs/alpha`、`method_plan`、`methods[]`、`tests[]`、`effects[]`、`multiplicity`、`conclusions[]`、`comparisons[]`、`cleaning`、`descriptives`、`transformations[]`、`inference_status`、种子/预算、假设/警告及产物路径；效应量保留定义、方向和适用的区间 |

`effective_kind` 支持 numeric（连续/离散数量）、boolean（二分类）、categorical（无序多分类）、ordinal（有序分类）、datetime；id/text/empty 是不可直接分析的状态。
统一采用多方法结果，不保留单方法 `method/method_label/reason/metrics/interpretation`、`legacy_primary` 或旧版本适配器；不为兼容添加 schema_version。
`kind/type` 分别保留为机器类型与中文类型标签，供当前 inspect/报告使用。无可计算推断时 `inference_status=descriptive_only`，各方法保留原因及可用描述，不伪装成功检验。
`total_rows` 为去掉全空行后的行数，`missing_pairs=total_rows-n` 包含转换失败和其余缺失配对；互斥分解见 `cleaning`。

新增 CLI 契约：`--col1-type/--col2-type auto|numeric|boolean|categorical|ordinal|datetime`，默认 auto；`--col1-order/--col2-order` 为 JSON 标量数组，仅用于 ordinal；`--seed` 默认沿用既有置换种子 20241102。
`--methods auto` 为默认，执行矩阵候选中适用的方法；也可显式指定逗号分隔的方法标识。重复标识去重，未知或与字段类型不兼容的方法在入口报错并给出适用清单；样本不足的候选保留状态和原因。CLI 默认输出多方法结果。

ordinal 必须由用户确认完整、无重复的水平顺序，例如 `["低","中","高"]`；不能按字母顺序猜测，也不能把等级间距当作数量间距。顺序包含全部观察到的非缺失值，可以包含本样本未出现的合法水平；漏项/重复项报明确错误。

数字低基数只产生类型建议；不自动把测量值改成分类。确认按分类处理后，有两个有效水平的无序分类归入 boolean；显式 ordinal 即使仅两个水平仍保留顺序。编码方向和原标签必须记录；反转二分类编码只改变有符号效应方向。

原始空单元格与明确缺失标记按统一策略处理；`无/否/0/false` 不得全局当作缺失。
保留每列转换失败的单元格数；行排除按全空行、含转换失败的配对、其他缺失配对依次归入互斥原因。
原始行数减去这些行排除数必须等于 N，不能将两列失败的单元格数直接相加后扣行。
id/text/empty/常量拒绝直接分析；疑似 ID 要先核对业务语义，不能只发警告后套 Pearson。

## 完整类型组合矩阵

五种支持类型共 15 个无序组合；交换列顺序应形成相同的方法集合，保留相应标签与编码方向。每行是默认候选集合，逐项校验适用性，不保证任何数据上都能做两个有效检验。

| 字段组合 | 同次执行的常见方法候选 | 必须交付的效应/解释 |
|---|---|---|
| numeric × numeric | Pearson、Spearman、Kendall τ-b | r/ρ/τ-b、适用的 Fisher-z CI；分别说明线性和秩关联 |
| numeric × boolean | 点二列相关、Welch t、Mann-Whitney U | r_pb、可定义的 Cohen's d、秩二列相关、两组摘要及 0/1 映射 |
| numeric × categorical | 单因素 ANOVA、Welch ANOVA、Kruskal-Wallis | η²/ω²、ε²、全部组摘要；Welch ANOVA 的均值推断配组均值/差异描述，不套经典 ANOVA 的 F/df |
| numeric × ordinal | Spearman、Kendall τ-b | ρ/τ-b、有序映射、并列秩校正；不假定等级等距 |
| numeric × datetime | 日期转 epoch 天后的 Pearson、Spearman、Kendall τ-b | 趋势方向、r/ρ/τ-b、时间单位及独立观测假设 |
| boolean × boolean | 2×2 卡方、双侧 Fisher、G 检验 | 带编码方向的 φ、Cramér's V、优势比；按稀疏规则分别校准 p |
| boolean × categorical | 列联表卡方、G 检验 | Cramér's V、观测与期望频数、互信息 I（nat，仅描述，和 G 存在代数关系） |
| boolean × ordinal | Mann-Whitney U、Spearman、Kendall τ-b | 秩二列相关、ρ/τ-b、分组等级频数；说明各方法高度相关，不能计票 |
| boolean × datetime | 时间戳的 Mann-Whitney U、日历特征筛选 | 时间位置的秩差异与日历模式分别解释；日历筛选仍是探索性子检验 |
| categorical × categorical | 列联表卡方、G 检验 | Cramér's V、完整频数、I（nat，仅描述）；不将派生效应当新增检验 |
| categorical × ordinal | Kruskal-Wallis、列联表卡方 | ε²、V、等级频数；前者用顺序，后者忽略顺序检验类别分布 |
| categorical × datetime | 时间戳的 Kruskal-Wallis、日历特征筛选 | 时间位置的秩差异与日历模式分别解释；不能用最低 p 代替整体独立性检验 |
| ordinal × ordinal | Spearman、Kendall τ-b | ρ/τ-b、两侧有序映射；方向随顺序定义解释 |
| ordinal × datetime | 日期转 epoch 天后的 Spearman、Kendall τ-b | ρ/τ-b、等级随时间的单调趋势；不宣称检出周期性 |
| datetime × datetime | 两日期转 epoch 天后的 Pearson、Spearman、Kendall τ-b | r/ρ/τ-b、日期范围；共同趋势不代表因果 |

方法标识固定为 `pearson/spearman/kendall_tau_b/point_biserial/welch_t/mann_whitney/anova/welch_anova/kruskal_wallis/chi_square/fisher_exact/g_test/datetime_features`。
`datetime_features` 的各日历特征按原稀疏规则使用卡方或 Fisher/置换校准；所有叶子检验保留特征与统计量标识，不生成伪造的容器 p。

## 多方法执行与对照契约

- 一次选择、一份清理结果、一次方法计划；所有方法共享同一完整配对样本。秩变换、0/1 映射和日历提取是显式派生，不按方法另删异常值、改分箱或偷偷改变 N。
- 默认执行全部适用候选。只剩一种可用方法时正常报告该方法与其余原因；没有有效推断但仍有可描述样本时输出 `descriptive_only`，不补造方法或 p。
- 每种方法交付分析问题、适用条件、统计量、效应量、原始 p、校正 p 和解释；同一统计量的渐近/精确/置换校准不重复列为不同方法。V、φ、I 和 d 是效应/描述量，不按其数量计检验次数。
- `multiplicity` 记录 `family_id`、有效 `test_ids`、`m`、`adjustment: holm` 和 alpha；同一次请求中所有有效叶子 p（包括相关检验与日历特征）构成一个 family。
  按原始 p 升序，校正值为 `min(1, max_{j≤i}((m-j+1)*p_(j)))`，再映回原检验；不适用/null p 不计入 m。
  效应量区间若未同步校正，必须标明是单项区间，不能表述为覆盖全部方法的同时置信保证。
- 显著性与摘要使用校正 p；原始 p 仅作透明呈现。Holm 可用于相关检验，但各 p 自身仍须满足其假设；不能用“多数显著”、最小原始 p 或最大效应代替综合解释。
- `conclusions[]` 按分析问题记录证据与限制；`comparisons[]` 记录方法标识、可比较依据、方向/证据差异和解释。不同原假设分别陈述，不强行合成一个“相关/独立”布尔值。
- Pearson/Spearman 不一致时说明线性、单调、离群值等可能影响，但不据此确定原因；均值检验与秩检验不一致时说明问题与假设不同。U、秩相关等可能等价或高度相关，多个一致结果不代表独立重复验证。
- 方法和校正范围在看 p 前确定，不能反复改方法/alpha/种子直到显著；用户改变计划属于新请求，不追溯覆盖先前结果。未知计算错误仍使分析失败，不伪装成某方法不适用。

## 检验有效性与结论契约

- 所有方法仅使用转换后的完整配对；在该子样本上重新检查类别数和变异。相关 N<3、有效分组不足两组或配对后常量，均返回可解释错误，不输出伪造 p。
- Pearson/点二列的参数检验针对零线性相关；Spearman/Kendall 渐近检验针对对应的零秩关联；Welch t、经典/Welch ANOVA 针对均值；U/KW 针对秩分布。
  置换 p 依赖独立观测下的可交换性，必须在 `null_hypothesis` 中记录对应假设，不能称为检验任意形式的依赖。
  U/KW 只有分布形状等附加条件满足时才能作位置/中位数解释；列联表分支明确使用分类变量独立性原假设。
- 所有适用双侧检验使用双侧 p；相关 N≤3 的 Fisher-z CI 不可用，完美相关不伪造零宽区间；CI 缺失需给理由。Spearman/Kendall 不直接套用 Pearson 的 CI。
- 2×2 独立列出双侧 Fisher；任一期望频数<5 时，卡方/G 各自用对应统计量置换校准，否则仅描述。
  非稀疏 2×2 卡方保留 Yates 校正；更大表任一期望频数<1 或超过 20% 单元格<5 时，卡方/G 均用对应统计量置换。效应 V 始终使用未校正 Pearson χ²。
  G 采用 `2*Σ O*ln(O/E)`，O=0 项贡献 0；非稀疏时用相应 df 的卡方渐近分布，不能借用 Pearson χ² 的 p。
- 稀疏表且 `--permutations 0` 时，卡方/G 标 `descriptive_only`、p=null；仍可执行适用的 Fisher，不根据不可靠近似下显著性结论。
- Spearman/Kendall N<30、U 任一组<10、KW 任一组<5 时，使用对应统计量的置换 p；其他情况可用已标明的渐近近似。禁用置换且近似条件不满足时只作描述；并列秩须修正，τ-b 分母退化时标不适用。
- Monte Carlo p 用 `(extreme+1)/(B+1)`；记录请求/实际 B、种子和判定方向，不静默增加或截减 B。默认 B=2000，显式说明估计精度。固定种子结果可重现。
- 经典 ANOVA 使用组数≤20、每组≥3、各组标准差>0 且最大/最小标准差≤3 的原有启用规则，未满足时标不适用；这不证明正态性。
  Welch t 每组≥2，Welch ANOVA 每组≥2 且各组方差>0 才可计算；不适用者保留原因，KW 可独立执行。所有请求的适用方法独立保留，不按最小 p 挑选代表方法。
- 零方差导致的 d、优势比或其他无限/未定义值使用 JSON null 和原因；JSON 不出现 NaN/Infinity。不能用 d=0 表示分母为零。未知内部计算错误应失败，不吞错后换检验。
- 日期筛选沿用 year/month/day/weekday，含非零时分时增加 hour/minute；仅分析有变异的特征，报告排除项；无有效特征则该方法不适用，其余方法继续。日期时区转换必须记录。
  各特征的原始 p 直接参与请求级 Holm，不先 Bonferroni 再作第二次校正，不提供日历子集的旧校正字段。
- 校正后 `p>=alpha` 表述为对应问题证据不足，不能证明独立、相同或无关系；多个相关系数接近零也不能排除非单调依赖。每个结论都引用相应检验，不挑选参考 p。

## 主链路

1. 接收字段和语义 → 转换并固定完整配对 → 形成方法计划 → 执行所有适用方法 → 对有效叶子 p 作 Holm → 分问题解释与对照 → 输出可追溯结果。
2. 字段本身无效 → 返回修正原因；个别方法样本/假设不足 → 记录该方法状态，其余适用方法继续；没有有效推断 → 描述结果及限制。

## Feature Task

- [x] T1 — 交付可覆盖的字段语义与一致清理契约，使数字分类、有序等级和合法否定值都按用户定义进入分析。
- [x] T2 — 交付五种类型全部 15 种组合的多方法计划、计算与效应量，使同一字段对可从多种适用视角获得可复查结果。
- [x] T3 — 交付小样本、稀疏数据及退化样本的推断边界，使不适用的统计量不会被解释为可靠结论。
- [x] T4 — 交付请求级多重检验校正与分问题对照解释，使方法差异、相关证据和推断限制不会被挑选显著结果掩盖。

2026-11-02 范围调整：取消原 T5。其兼容目标由用户明确移除；多方法结构化输出、skill 指引和分支回归已随 T1–T4 交付，本轮清理后执行 Feature 整体验收，不另立重复任务。

## 验收锚点与执行入口

以下为完整 Feature 的验收清单。取消兼容要求后，用同一多方法契约验收全部 A1–A9；具体执行结果见完成证据。

| 用例 | 机器断言 |
|---|---|
| A1 类型/清理 | `有/无`、`是/否`、数字 0/1 均保留合法观测；数字分类覆盖有效；有序漏项/重复项拒绝；计数守恒；ID/空列/高基数文本拒绝直接分析 |
| A2 组合覆盖 | 参数化 15 组合及反向输入，校验完整方法集合、共同 N、每项适用状态和效应方向；覆盖新增 Kendall、Welch ANOVA、G 检验及所有既有分支 |
| A3 数值正确性 | 用已核对的参考常量验证 r/ρ/τ-b/φ、χ²/G/Fisher、Welch t/ANOVA、U/KW、η²/ε²/I，非随机结果容差≤1e-6；来源随测试固化，生产不引入 SciPy |
| A4 边界 | 配对后单一类别、N<3、零组内方差、完全相关、并列秩、小样本置换及 `B=0`；未定义指标为 null，有理由；固定 seed/B 精确复现；Monte Carlo p 不为 0 |
| A5 日期 | 日期转天数单位/时区明确；日历子检验和时间秩检验使用同一配对并进入同一 Holm family；无有效日历特征时其他方法仍可用；不存在日历子集旧校正字段 |
| A6 结果交付 | CSV/Excel CLI 与名称/编号选列可用；stdout 与落盘 JSON 严格可解析且相同；Markdown 完整展示 methods/tests/effects 及 Holm；图表/CSV 可读；无旧单方法字段 |
| A7 方法计划 | auto 默认执行完整适用集合；显式子集去重、未知/类型不兼容报错；显式子集不触发额外方法；单方法可用和全描述均可解释；改 p 不改变预定计划，校准变体不重复计数 |
| A8 校正 | 原始 p `[0.01,0.04,0.03]` 的 Holm 值为 `[0.03,0.06,0.06]`；原顺序恢复、并列 p、m=0/1、null 排除与日期叶子计数正确；相关方法也纳入 family |
| A9 对照 | 固定差异结果可按问题解释，不按最小 p/多数决；端到端单调非线性、并列等级、异方差分组、稀疏类别样本展示全部方法；对称 U 形数据的零相关不能被解释为独立 |

完整 Feature 验收入口：`python3 -m unittest discover -s tests/dasci-relationship -p 'test_statistics_*.py'`，最终覆盖 A1–A9。T1–T4 当前有 `test_statistics_semantics.py`、`test_statistics_methods.py`、`test_statistics_inference.py` 和 `test_statistics_interpretation.py`；发布前运行 skill-creator 的 `scripts/quick_validate.py skills/dasci-relationship`。

每个方法必须至少有正常样本和关键边界断言；不以只检查方法名称或文案的测试代替数值验证。Feature 验收要求 selected=executed=passed，failed=skipped=not_executed=0。

## 完成证据

以下保留各轮验收时的状态与边界；当前能力及原 T5 的处理以末尾 S8 记录为准。

### S4 / T1（当轮验收记录）

- 2026-11-02，S4 / T1 完成：新增显式类型覆盖与有序顺序校验，保留推断/有效类型、来源、原标签和编码；数字低基数只建议，疑似数值 ID 不再仅警告后进入 Pearson。
- CSV/Excel 采用统一缺失策略，保留 `无/否/0/false`；记录转换失败单元格及互斥行排除，共同配对在所有旧分支固定，过滤后重检变异/类别数。Markdown 追加清理明细。
- `test_statistics_semantics.py`：selected=executed=passed=29，failed=skipped=not_executed=0；覆盖 A1，以及 CSV/Excel、名称/编号、JSON/Markdown/图表和旧统计分支的必要回归。未宣称完整 A2–A9 通过。
- Python 语法编译与 skill-creator 快速校验通过；一轮本次 diff 审查完成。现场无有效 Git 元数据，以切片前原文/SHA-256 基线核对允许范围，未修改统计库或绘图库。
- 本地证据：`evidence/dasci-relationship/relationship-statistics-coverage/t1/`，包含验收日志、摘要、基线差异和源码摘要；由 `/evidence/` 忽略规则排除，未入库。
- 有序语义准备完成，有序统计计算仍明确拒绝并留待 T2；15 组合多方法、小样本推断校准、Holm、完整 v2 结果，以及另外两个 Feature 均未交付。本切片 WIP=0，停止。

### S5 / T2

- 2026-11-02，T2 完成：新增统一方法计划与计算入口，覆盖五类型全部 15 无序组合及反向输入；默认 auto 执行矩阵候选，显式方法子集去重并校验适用性，不额外执行未请求的兼容代表方法。
- 补齐无 SciPy 运行依赖的 Kendall τ-b（并列秩校正，O(N log N)）、Welch ANOVA 与 G 检验；交付 r/ρ/τ-b、r_pb、d、秩二列相关、η²/ω²、ε²、V/φ、优势比、I（nat）和对应分组/频数描述。Welch ANOVA 保留独立 F/df 和组均值，不借用经典 ANOVA。
- 每个候选共享 T1 固定样本，保留分析问题、条件、统计量、效应定义/方向及 ok/descriptive_only/not_applicable 状态；ordinal 按显式顺序运行，日期保留 epoch 天数和时区转换，各日历特征独立记录，无容器 p。
- CLI 接入 `--methods` 与 `--seed`；原 metrics 从本次可用代表结果派生。现有 Markdown 展示全部候选、效应、映射与原因；未校正的原始 p 明确标为探索性，不产生综合显著性结论。
- 冻结测试 selected=executed=passed=54，failed=skipped=not_executed=0；含 15 组合双向计算、15 组合 CLI/JSON/Markdown 落盘、方法子集、共同 N/标签、稀疏校准和 T1 回归。固定数值参考来源随测试记录（SciPy 1.16.3 仅用于开发核对，生产无依赖）。同时修正受影响 U 正态近似在 U=均值时连续性校正越过均值的问题，断言 p=1。
- 语法编译、skill 快速校验、文档/尺寸/依赖/范围检查通过；一轮本次 diff 审查完成。现场无有效 Git 元数据，以切片前原文/SHA-256 基线核对八个允许路径；本地日志、摘要、差异及示例报告缓存于 `evidence/dasci-relationship/relationship-statistics-coverage/t2/`，未入库。
- T3 小样本秩置换校准及完整退化边界、T4 Holm/方法对照、T5 完整 v2/兼容验收仍未完成；当前小样本秩检验仅描述、p=null，校正字段为 null。sheet 选择与统一 HTML 模板未进入实施。当前 WIP=0，停止。

### S6 / T3

- 2026-11-02，T3 完成：Spearman/Kendall N<30、U 任一组<10、KW 任一组<5 使用各自秩统计量置换，保留平均秩、并列校正、组大小和共同配对；相关/U 双侧、KW 上尾。B=0 时保留描述效应及明确原因，p=null；达到阈值后保留标明的渐近近似。
- Monte Carlo p=(extreme+1)/(B+1)，请求 B 精确执行、不加下限/不截减；每个叶子记录 requested/used、seed、alternative、extreme、分辨率和近似 MC 标准误。秩相关置换明确固定边际重新配对的原假设与独立观测可交换性，不包装为万能独立性检验；原始 p 尚未校正。
- 稀疏 χ²/G 按各自统计量校准并记录同一精度契约；日历叶子沿用稀疏规则，无容器 p。验证非稀疏 2×2 的 Yates 与未校正 V 分离，Fisher 精确 p 在无限优势比时仍可用，优势比以 null 和原因保留。
- Pearson N≤3/完全相关的 Fisher-z 区间为 null；Spearman 不借用 Pearson 区间。Welch 零标准误不适用且 d=null 并给理由；KW 全并列明确失败，禁止用默认校正值掩盖退化。相关 N<3、配对后常量/单组、ANOVA/Welch 方差与样本量限制及未知内部异常传播均有断言；保留 T1 的无效字段入口拒绝。
- 新增 22 个推断测试，使用独立逐项公式、固定 seed Monte Carlo 和枚举全部索引排列核对四类秩统计量；覆盖阈值两侧、B=0/1/2003、稀疏 χ²/G 的独立参考、日期叶子共同 N/时区、退化效应和区间、严格 JSON、Markdown 及受影响旧直接调用。
- 冻结统计测试 selected=executed=passed=76，failed=skipped=not_executed=0；Python 语法编译、skill-creator 快速校验及文档/状态/尺寸/无 SciPy 导入检查通过。仅运行三份统计模块测试，没有声明完整 Feature A1–A9 通过。
- 一轮本次 diff 审查完成；清理去除吞错后产生的冗余判空。现场无有效 Git 元数据，以本轮原文/SHA-256 基线核对仅八个允许文件变化；未初始化 Git、提交或推送。证据缓存 `evidence/dasci-relationship/relationship-statistics-coverage/t3/`，含验收日志、acceptance.json、基线/diff 和 8 行有序×数值的 report.md/result.json 样例（B=2000、seed=701），未入库。
- T4 Holm/分问题对照、T5 完整 v2/兼容验收，以及 sheet 交互和统一 HTML 模板仍待后续任务。本切片验收即停，WIP=0。

### S7 / T4

- 2026-11-02，T4 完成：同一次请求的全部有效叶子 p 进入一个 Holm family，包含相关方法、reference 和日历叶子；null p 排除，效应、容器和校准变体不重复计数。校正保留原始 p/执行顺序并记录 family/m/alpha，只有 p_adjusted<alpha 才拒绝对应原假设。
- 新增 `multiplicity/conclusions/comparisons`；结论按线性、单调、均值、秩分布、类别独立性与日历问题组织，逐项引用 test/effect 及校正证据，不按最小 p、最大效应或多数决生成整体“相关/独立”。不可推断项保留原因；单方法、全描述及全不适用都有输出。
- 对照覆盖相关/秩、经典/Welch、均值/秩、U 与二分类秩相关、忽略等级顺序的 χ² 与 KW、类别校准，以及时间位置/日历模式；有符号效应保留编码与方向。方法差异仅说明可能影响，不确定归因；相关检验不作为独立重复验证。
- CLI 兼容 metrics 保留明确标识的原始 p，并增加 Holm p；interpretation 来自分问题结论。Markdown 展示检验族、原始/校正 p、各项判断、结论限制与对照；日期 CSV/Markdown 使用同一请求 Holm，不先 Bonferroni。skill 指引同步当前推断口径，区间仍标单项且不提供同时覆盖保证。
- 新增 21 个测试：Holm 固定参考 [0.01,0.04,0.03]→[0.03,0.06,0.06]，并列/累计最大/截1、m=0/1/null/alpha 边界及临界值显示、reference/日期同族、效应不计数、方法计划不随 p 变化、混合证据/方向/不可用及 U 形零相关限制；单调非线性、并列等级、异方差、稀疏类别和日期 CSV 的端到端结果可追溯。
- 冻结测试 selected=executed=passed=97，failed=skipped=not_executed=0；T1–T3 三份回归及 T4 新增一份全部执行。Python 语法编译、skill-creator 快速校验、文档链接/状态/尺寸/层级/尾随空白、生产与测试无 SciPy 导入检查通过。
- 一轮本切片 diff 审查完成，未更改统计原语、类型/清理、方法选择或绘图库；现场仍无有效 Git 元数据，以本轮原文/SHA-256 基线核对九个允许路径，没有初始化 Git、提交或推送。本地证据 `evidence/dasci-relationship/relationship-statistics-coverage/t4/`（未入库），包括日志、acceptance.json、基线/diff 和合成差异样例 report.md/result.json。
- 差异样例 N=40：Pearson r≈-0.203，Holm p≈0.210；Spearman ρ≈0.854，Holm p≈5.12e-12；Kendall τ-b=0.9，Holm p≈8.58e-16。线性与单调问题分别解释，旧代表仍为 Pearson，不按显著性改选方法；样例仅用于演示解释边界。
- T5 完整 v2 输出/兼容验收、sheet 选择和统一 HTML 模板尚未完成，不声明整个 Feature 已完成；当前 WIP=0，停止，不自动进入 T5。


### S8 / 取消兼容与 Feature 整体验收

- 2026-11-02，用户明确无需兼容。取消原 T5：其兼容目标删除；多方法结构化结果、skill 指引和全分支回归已随 T1–T4 交付，本轮按 A1–A9 进行 Feature 完成验收，不将 T5 标记为“已实施”。
- 删除五个旧单方法分析入口、旧 choose_method 和专用辅助函数；删除 legacy_primary 选择、单方法 method/method_label/reason/metrics/interpretation 及 tests.role，不提供旧 schema 适配器。Markdown 直接消费统一多方法契约，移除重复解释与旧 Bonferroni 回退。
- 保留当前有用途的类型标签、来源、清理计数和 Markdown/图像路径；CSV/Excel、名称/编号选列、多方法及显式子集、图表与 CSV 均通过当前主链路回归。skill 结果读取指引同步到统一契约，后续选择/统一报告规格移除兼容约束；固定 HTML 模板要求保留，尚未实施。
- 本轮先更新契约测试，旧实现因保留旧字段出现预期失败；删除兼容层后通过。移除两个仅服务旧入口的测试，新增四类图表 PNG 解码/正文引用，以及全部描述/全部不适用的 CLI 落盘验证；强化 15 组合 JSON/Markdown 逐项数值与引用核对。
- 最终四份统计测试 selected=executed=passed=97，failed=skipped=not_executed=0，覆盖 A1–A9；Python 语法编译、skill-creator 快速校验、规范/依赖/范围/空白检查通过。现用统计原语、类型清理、推断与绘图函数通过基线 AST 等价核对；本轮只移除旧路径及适配字段，没有重写统计算法。
- 一轮本次基线 diff 审查完成。现场无有效 Git 元数据，以切片前原文/SHA-256 核对允许范围，未初始化仓库。本地证据 `evidence/dasci-relationship/relationship-statistics-coverage/no-compat/` 保存测试、语法、skill、契约/范围检查日志、acceptance.json、基线/diff 和 N=40 的 CLI 样例，未入库。
- 合成样例同次输出 Pearson、Spearman、Kendall；Holm p 分别约 0.209562、5.123e-12、8.584e-16，保留线性/秩证据差异及方法对照。stdout 与 result.json 相同，Markdown 包含全部方法/结论/对照，PNG 实际生成。
- 统计 Feature 完成并移入 archive，backlog 标记完成；工作台 WIP=0，验收即停。工作表/字段选择体验与统一 HTML/Markdown 报告 Feature 仍待实施。
