---
name: dasci-relationship
display_name: "数据科学-关系分析"
display_name_en: "Data Science - Relationship Analysis"
description: >-
   用于分析数据表格的字段相关性、两列之间的关联及组间差异。支持 CSV/Excel 的数值、分类、有序和日期字段，输出统计结论、图表及 HTML/Markdown 报告；缺少文件或字段时引导用户选择。
   Use for correlation analysis, association analysis, or group comparisons between two columns in CSV/Excel tables. Supports numeric, categorical, ordinal, and date fields. Generate statistical findings, charts, and HTML/Markdown reports; guide file and column selection when needed.
   触发示例 / Example prompts：分析数据表格的字段相关性、做相关性分析、看看这两列有没有关系；analyze correlations between columns, run a correlation analysis, check whether two columns are related, compare groups in a spreadsheet.
   不用于因果推断或预测建模。Not for causal inference or predictive modeling.
description_zh: "分析 CSV/Excel 两个字段的相关性、关联与组间差异，生成统计结论、图表及 HTML/Markdown 报告。"
description_en: "Analyze correlations, associations, and group differences between two CSV/Excel columns, with statistical findings, charts, and HTML/Markdown reports."
category: "数据科学"
version: "1.4.1"
author: "dasci"
---

# 表格字段关系分析

一次分析两个字段，在共同配对样本上运行适用的多种方法，并用中文解释发现、差异与限制。用户只提出分析意图时，先补齐输入；不要求先报出文件格式、列名或统计方法才使用本技能。

## 运行入口

宿主提供 `load_workspace_dependencies` 时，用它返回的 Python 绝对路径；否则用环境中的 `python` 或 `python3`。脚本和资源均相对本次技能加载结果的 **base directory** 定位，不从当前目录猜路径。

```text
<python> <skill_dir>/scripts/data_relationship.py select --request <临时JSON路径>
```

请求 JSON 由智能体准备，用户只需提供路径、名称/编号和自然语言选择。Windows PowerShell 使用 `& "<python>" "<script>" ...`；其他 shell 对路径正确加引号。运行依赖 pandas、numpy 和可选绘图依赖 Pillow，不假设 SciPy 可用。

## 执行流程

1. **补齐选择。** 先读 [选择协议](references/selection-workflow.md)，补齐文件与 sheet；Excel 即使只有一个 sheet 也不代选。WorkBuddy 有 `widget_guidelines` 和 `show_widget` 时，先读取 interactive 指引，select 传 `host.tools=["widget_guidelines","show_widget"]`，脚本自动返回对话内控件。**sendPrompt 是控件内部由宿主注入的 JavaScript 函数，不是工具，不要求它出现在工具列表。** 其他宿主按实际 schema 填 questions/max_questions；max_options 仅填声明的硬上限，未声明就省略。
2. **完整列出字段，在对话中提交 X/Y。** 按返回的 `question.mode` 呈现：`widget` 时将 `question.widget` 原样传给 show_widget，结束本轮等待用户提交；`tool` 时将 `tool_arguments` 的完整 X/Y 选项传入提问工具。DeepSeek Harness 不擅自缩减选项；WorkBuddy 使用上述对话内滚动控件，不因工具列表没有 sendPrompt 而退回文字。不得挑常用字段、重排、合并字段或把候选塞进题干；目录预览分页不限制候选。按 x/y 答案组装 `action.pair`，控件同时回传 `context_key`，携带完整 state 继续 select。工具确实缺失或控件调用实际报错时说明具体原因，列完整编号目录并收集 `A → B`。不默认打开外部页面；完整且语义齐全的 pair 直接 ready，默认值、部分答案或等待状态不能触发分析。
3. **展示执行摘要。** 列出文件、sheet、两字段编号/名称/有效类型、共同 N、`summary.plot` 横纵轴和候选方法；`ready` 后直接执行，不再等待确认。用户预先明确完整输入时也直接运行；未指定方向的直接 CLI 请求保留脚本默认布局。交换仅改变绘图方向，不交换统计字段；派生图按各自的 `figures[].axes` 解读。候选清单不保证全部方法最终可计算。
4. **执行分析。** 需要调用参数或读取结果时查阅 [分析契约](references/analysis-contract.md)。仅在 `select` 返回 `ready` 后使用其 `analysis_args`；可追加用户要求的输出/统计参数，保留字段、语义、方法和轴。命令失败如实解释，不伪造结果，不重跑尚未结束的任务。
5. **核对本次发布。** 等待退出码为 0、`ok=true`、`publication.status=complete`；核对 `result.json` 与返回对象一致，运行目录和 HTML 的标识对应 `publication.run_id`。使用本次返回的路径，不能凭已有 HTML 判断完成。
6. **解释与交付。** 按下面的解释规则说明发现；需要核对类型、方法或小样本等条件时再读 [统计细则](references/statistical-guide.md)。交付前读 [报告指引](references/report-workflow.md)，完成必要核验、解释准备和自行创建的临时文件清理后，给出 HTML 阅读入口与 Markdown 保存入口，再结束回复。

## 解释与交付规则

- 字段必须来自用户选择；疑似 ID 先确认业务含义，常量/空列/高基数文本按原因改选或预处理。数字分类需业务确认；有序字段必须给出完整业务顺序，不猜排序或等距，也不把 `无/否/0/false` 全局当作缺失。
- 方法计划在看 p 值前固定，所有方法使用同一共同样本；逐项读取 `methods/tests/effects/conclusions/comparisons` 的状态、引用与限制，不挑最小 p，不按显著方法数量投票。保留清理计数、编码方向和实际 warnings。
- 结论依据请求级 Holm 校正及记录的决定，包含全部有效叶子检验与日历特征；null p 不补值。`descriptive_only` 只能描述，`mixed_evidence` 分项解释；区间是单项区间，不承诺同时覆盖。完整字段口径见分析契约。
- 先用 1–3 句说明发现、方向和有效 N，再列实际分析方法与限制。方法身份直接可见，不用观察角度替代或折叠；术语仅首次中英文对照。FWER 用“多次检验的整体误报风险”，避免“家族错误率”。
- 统计上有证据不等于关系强，证据不足不等于没有关系；关联不证明因果，方法差异的可能影响不等于已确定原因。至少说明一条实际限制或假设。
- 报告显示通常 4 位小数，极小数用 6 位或科学计数法；判断用原值，JSON/CSV 保留完整精度。长内容和 JSON 可展开，统计详情保留所有方法、原始/校正 p、效应、区间和引用。
- HTML 是默认阅读入口，图已在正文中，CSV 作为复查附件。缺图时说明原因；单 HTML 不包含 CSV，完整分享使用整个输出目录。必需报告或附件写入失败不能声称完成；报告资源使用随技能分发的固定模板，不临时另写页面。
