# dasciskills

面向智能体的数据科学技能集合（Data Science Skills）。每个技能将分析流程、Python 脚本、报告模板和参考契约放在独立目录中，帮助用户用自然语言完成数据分析，并保留可复查的统计结果与报告。

技能统一使用 `dasci-` 前缀。目前提供 **`dasci-relationship`（数据科学-关系分析）**：分析 CSV / Excel 中两个字段的相关性、关联与组间差异，生成图表、HTML 阅读版、Markdown 保存版和机器可读结果。

## 技能目录

| 技能 | 用途 | 入口 |
|---|---|---|
| `dasci-relationship` | 根据数值、二分类、多分类、有序和日期类型，选择适用的多种统计方法分析两个字段 | [技能说明](skills/dasci-relationship/SKILL.md) |

当前技能版本为 **1.4.1**，以技能目录内 `SKILL.md` 的版本声明为准。

## 能做什么

- **引导选择数据。** 检查文件、Excel 工作表和字段类型；支持按名称或稳定编号选择字段，明确图表的 X / Y 方向。
- **按类型运行多种方法。** 在同一份有效配对样本上计算适用方法，保留样本清理记录、效应量、原始 p 值、Holm 校正结果及方法不适用的原因。
- **生成可复查报告。** HTML 与 Markdown 来自同一报告模型，保留结论、方法差异、图表、假设与限制；JSON 和适用的 CSV 附件用于复查。
- **离线阅读与独立使用。** HTML 内嵌样式和成功生成的图片；分析脚本也可直接通过命令行运行。

常见方法包括 Pearson、Spearman、Kendall τ-b、点二列相关、Welch t、Mann–Whitney U、ANOVA、Welch ANOVA、Kruskal–Wallis、卡方、Fisher 与 G 检验。实际执行集合取决于字段类型、共同样本和方法条件，详见[统计方法与适用限制](skills/dasci-relationship/references/statistical-guide.md)。

## 环境准备

需要 Python 3。以下命令从仓库根目录执行，使用 Bash 语法；本次 README 示例在 Python 3.12 环境验证。

建议为项目建立独立环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install numpy pandas openpyxl Pillow
```

| 依赖 | 用途 |
|---|---|
| `numpy`、`pandas` | 核心数据读取、清理与统计计算 |
| `openpyxl` | 读取 `.xlsx` / `.xlsm`；仅分析 CSV / TSV 时不需要 |
| `Pillow` | 可选绘图依赖；缺少时仍可生成统计结果和双格式报告，并说明无图原因 |
| 中文字体 | 绘图需要可用的中文字体，脚本会查找微软雅黑、苹方、Noto Sans CJK 等预设路径 |

运行时不依赖 SciPy。旧版 `.xls` 读取取决于环境是否已有相应引擎，建议先另存为 `.xlsx`。

## 在智能体中使用

将完整的 [`skills/dasci-relationship/`](skills/dasci-relationship/) 目录放到宿主配置的技能加载位置，保留 `SKILL.md`、`scripts/`、`assets/` 和 `references/`。安装后重新加载技能或开启新会话，确认加载名称为 `dasci-relationship`。

脚本与资源应相对本次加载结果的 **base directory** 定位。DeepSeek Harness 可能同时存在工作区和用户目录中的副本，更新时应核对实际加载位置；仅复制说明文件或主脚本不足以更新完整技能。宿主提供依赖加载工具时，使用它返回的 Python 绝对路径。详细流程见[技能说明](skills/dasci-relationship/SKILL.md)。

可以直接提出需求：

```text
分析这份销售表里“销售额”和“利润”的关系，并生成报告。

看看这个 Excel 中不同部门的“满意度”有没有差异。

分析“服务等级”和“续费意愿”的关联。服务等级按低、中、高排序。
```

缺少文件、工作表、字段或业务类型时，智能体会引导补齐；Excel 即使只有一个工作表，也需要用户明确选择。字段选择同时确定绘图方向，方向只影响展示，不代表因果角色。

DeepSeek Harness 使用原生提问；WorkBuddy 在提供 `widget_guidelines` 和 `show_widget` 时使用对话内滚动控件。当前任务记录中，WorkBuddy 新版真实界面以及报告精简后的浏览器视觉验收仍待完成，进度见[需求池](tasks/backlog.md)。

## 命令行快速体验

以下示例生成一份 40 行的演示数据，再检查字段并执行分析。

### 1. 生成示例 CSV

```bash
python3 - <<'PY'
import csv

with open("demo.csv", "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(["销售额", "利润"])
    for i in range(1, 41):
        writer.writerow([100 + i * 10, 20 + i * 3 + (i % 5 - 2) * 4])
PY
```

### 2. 查看字段与类型

```bash
python3 skills/dasci-relationship/scripts/data_relationship.py inspect \
  --input demo.csv \
  --all-columns
```

### 3. 分析两个字段

```bash
python3 skills/dasci-relationship/scripts/data_relationship.py analyze \
  --input demo.csv \
  --col1 "销售额" \
  --col2 "利润" \
  --plot-x col1 \
  --out ./output/demo
```

命令向标准输出写入 JSON。成功时退出码为 `0`，并返回 `ok: true`、`publication.status: "complete"`、`report_html_path`、`report_md_path`、`result_path` 和 `out_dir`。用本次返回的 `report_html_path` 打开报告。

每次成功运行的产物位于 `./output/demo/run-<run_id>/`；`--out` 指定的是父目录，不要拼接成 `./output/demo/report.html`。

### Excel 与常用参数

Excel 先列出工作表，再指定工作表查看字段和分析。将下例的文件、工作表与列名替换为实际值：

```bash
python3 skills/dasci-relationship/scripts/data_relationship.py inspect \
  --input "销售数据.xlsx"

python3 skills/dasci-relationship/scripts/data_relationship.py inspect \
  --input "销售数据.xlsx" --sheet "明细" --all-columns

python3 skills/dasci-relationship/scripts/data_relationship.py analyze \
  --input "销售数据.xlsx" --sheet "明细" \
  --col1 "销售额" --col2 "利润" --out ./output/sales
```

| 参数 | 用途 |
|---|---|
| `--sheet-index N` | 用从 1 开始的物理编号选择工作表 |
| `--col1-index N` / `--col2-index N` | 用从 1 开始的物理编号选择列，适合重名列 |
| `--col1-type TYPE` / `--col2-type TYPE` | 按确认的业务定义指定 `numeric`、`boolean`、`categorical`、`ordinal` 或 `datetime`；默认 `auto` |
| `--col1-order JSON` / `--col2-order JSON` | 有序分类必须提供完整顺序，例如 `'["低","中","高"]'` |
| `--methods spearman,kendall_tau_b` | 指定适用的方法子集；默认 `auto` |
| `--plot-x auto\|col1\|col2` | 指定绘图横轴，另一字段为纵轴，不交换统计输入 |
| `--alpha 0.05` | 显著性水平，默认 `0.05` |
| `--permutations 2000` / `--seed 20241102` | 置换次数与随机种子；默认值如左，`0` 次禁用置换，需要该校准的方法仅作描述 |
| `--no-chart` | 跳过绘图，保留统计结果、报告和坐标计划 |

完整参数可通过 `python3 skills/dasci-relationship/scripts/data_relationship.py analyze --help` 查看。智能体选择流程使用 `select --request <JSON路径>` 推进，协议见[选择工作流](skills/dasci-relationship/references/selection-workflow.md)，结果字段见[分析契约](skills/dasci-relationship/references/analysis-contract.md)。

## 输出与分享

```text
output/demo/run-<run_id>/
├── report.html             # 默认阅读入口，样式与成功生成的图片内嵌
├── report.md               # 同源 Markdown 保存版
├── result.json             # 完整机器结果与复现信息
├── charts/                 # 实际成功生成的 PNG 图表（有图时）
└── *.csv                   # 本次分析适用的复查附件
```

CSV 附件按分析类型生成，包括列联表 `contingency.csv`、期望频数 `expected_counts.csv`、分组摘要 `group_summary.csv` 或日历特征 `datetime_features.csv`，并非每次都有。

- **阅读正文和图表：** 单独复制 `report.html` 即可离线阅读。
- **保存 Markdown：** 连同 `charts/` 等配套资源保存，图片使用相对路径。
- **完整复查与分享：** 复制整个运行目录；单文件 HTML 不包含 CSV 附件。

每次分析在独立目录完成生成与核验后发布，保留之前的成功结果。以本次命令返回的运行标识和路径为准。更多交付说明见[报告工作流](skills/dasci-relationship/references/report-workflow.md)。

## 数据与统计边界

- 输入应是第一行作为表头的规整二维表。多行表头、前置说明、合并单元格需要先清理；Excel 公式应先计算并保存缓存结果。
- 一次分析两个字段。疑似 ID、常量、空列和高基数文本不能直接作为正常分析字段；数值分类编码需要业务确认，有序字段需要完整业务顺序。
- 各方法使用相同的有效配对样本，记录缺失与转换失败。样本量不足或假设不满足时，可能仅给出描述结果或不适用原因。
- 推断结论依据请求级 Holm 校正，效应量用于说明关系大小；统计证据不等于关系强，证据不足也不等于没有关系。结果用于观察性关系分析，不提供因果推断或预测建模。
- 全文件读取与统计计算由 Python 在执行环境中完成。智能体上下文仍可能包含字段信息、少量预览值、统计结果和报告内容；实际数据处理边界还取决于宿主配置。

## 项目结构

```text
dasciskills/
├── skills/
│   ├── dasci-relationship.png      # 技能展示图片
│   └── dasci-relationship/         # 完整技能运行目录
│       ├── SKILL.md               # 技能入口、触发描述与执行规则
│       ├── scripts/               # 选择、统计、绘图和报告脚本
│       ├── assets/                # 报告模板、主题与字段选择控件
│       └── references/            # 工作流、调用契约与统计细则
├── tests/dasci-relationship/       # 自动化测试、fixtures 与视觉验收工具
├── tasks/
│   ├── backlog.md                 # Feature 级需求与状态
│   ├── active_task.md             # 当前 Atomic Slice 工作台
│   ├── lessons.md                 # 可复用的 Skill 构建规则
│   ├── specs/                     # 进行中的特性规格
│   └── archive/                   # 已完成并归档的规格
├── AGENTS.md                      # 协作与任务执行约束
├── LICENSE
└── README.md
```

本地验收证据放在 `evidence/`，该目录已被 Git 忽略，不随技能运行目录分发。分发技能时排除测试、证据和 `__pycache__` 等缓存，保留完整运行资源。

## 开发与验证

新建或维护技能时，参考 [Skill 构建简明规则](tasks/lessons.md)。

修改前先阅读 [AGENTS.md](AGENTS.md)、[需求池](tasks/backlog.md) 和[当前工作台](tasks/active_task.md)，冻结本轮边界、允许文件与验收命令。开发时只运行当前改动对应的测试；完整技能回归可使用以下入口：

```bash
python3 -m pip install beautifulsoup4 markdown-it-py
python3 -B -m unittest discover -s tests/dasci-relationship -p 'test_*.py' -v
```

测试还使用前述运行依赖。字段控件与网页选择器的 JavaScript 测试需要 Node.js，缺少时相关用例会跳过；检查最终测试输出后再判断覆盖情况。

浏览器视觉验收工具为 [`tests/dasci-relationship/report_visual_check.py`](tests/dasci-relationship/report_visual_check.py)，额外需要 Chromium、`websockets`、Markdown 渲染依赖和中文字体；这些属于验收环境，不是正常分析的运行依赖。宿主交互与浏览器视觉效果需要在对应环境单独验收。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
