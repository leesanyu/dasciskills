# 产品需求池

数据科学技能系列使用 `dasci-` 前缀（data science）；关系分析技能名为 `dasci-relationship`，运行资源、测试与证据分别按技能归入 `skills/`、`tests/`、`evidence/`。

| 状态 | Feature | 场景、问题与可观察结果 | 规格 |
|---|---|---|---|
| [x] | relationship-statistics-coverage | 对 CSV / Excel 做两字段分析的用户，需要从多个统计视角理解不同类型字段的关系；补齐类型语义并在一次请求中运行多种适用的常见方法，输出经校正的证据、效应量和结果差异说明。 | [不同类型字段的多方法关系分析](archive/feat-relationship-statistics-coverage.md) |
| [x] | table-selection-experience | 在含多个 sheet 或较多字段的 Excel 中选择分析对象的用户，容易被长列表与重复确认打断；提供分步预览、稳定编号、类型修正与局部纠错，使选择明确且可追溯。 | [工作表与字段选择体验](archive/feat-table-selection-experience.md) |
| [x] | unified-analysis-report | 阅读、分享和留存分析结果的用户，需要跨次分析保持一致的视觉风格，并在同一报告中理解多方法证据、差异与图表；用随 skill 分发的统一 HTML 模板生成展示版，同源生成 Markdown 保存版，离线可读且可追溯。 | [统一分析报告](archive/feat-unified-analysis-report.md) |
| [x] | plot-axis-selection | 在 CSV / Excel 中选择两字段并阅读关系图的用户，需要在分析前知道并能调整横纵轴；选择摘要明确绘图方向，报告与实际图保持一致，调整展示方向不改变统计输入与结果。 | [字段选择与绘图轴指定](archive/feat-plot-axis-selection.md) |
| [x] | skill-publication-layout | 维护和发布数据科学技能系列的开发者，需要统一技能名称并分离运行资源、测试与证据；dasci-relationship 使用独立发布目录，迁移后测试、调用和证据入口仍可用。 | [dasci 技能命名与发布目录](archive/feat-skill-publication-layout.md) |
| [x] | skill-discovery-guidance | 通过自然语言发起表格字段相关性分析的用户，需要智能体识别适用技能并补齐输入；描述明确匹配真实请求，入口精简且详细契约可按需查阅。 | [技能触发与精简指引](archive/feat-skill-discovery-guidance.md) |

| [-] | ordered-field-picker | 在 DeepSeek Harness / WorkBuddy 中选择两字段的用户，需要在当前对话中查看完整字段、明确提交 X/Y，无须额外网页或后置换轴，实际图与选择一致。 | [字段选择与绘图方向合并](specs/feat-ordered-field-picker.md) |
| [-] | report-reading-labels | 阅读和分享 HTML/Markdown 报告的用户，需要减少重复坐标提示并识别报告来源；正文只在图注说明横纵轴，页尾统一显示中文名称与版本。 | [报告坐标说明与页尾精简](specs/feat-report-reading-labels.md) |

统计覆盖、选择体验、统一报告、绘图轴指定、技能发布目录迁移与触发/精简指引均已完成并归档。字段与方向合并已提供完整原生选项与 WorkBuddy 对话内滚动控件，用户确认 DeepSeek Harness 选择可用；S29 修复 WorkBuddy 控件能力误判，83 项自动化、实际宿主桥接与 22 资源独立包通过。WorkBuddy 新版真实界面仍待验收，保持进行中；外部安装副本未同步。

报告坐标与页尾精简已实现，40 项自动化及五类实际双格式报告核验通过；真实浏览器因启动失败未完成验收，保持进行中。
