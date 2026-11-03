# Feature：技能触发与精简指引

- 标识：`skill-discovery-guidance`
- 状态：已完成并归档。
- 适用对象：用自然语言提出表格字段关系问题的用户，以及发现和执行技能的宿主智能体。

## Non-Goals

- 不改统计、选择、绘图、报告的运行代码、依赖和测试，不更改技能名称或目录。
- 不增加宿主专用元数据，不更新外部安装，不把描述校验等同于真实模型路由成功。

## 业务意图

用户说“分析数据表格的字段相关性”时，技能目录描述应明确说明这是本技能的使用场景；没有文件或字段时仍可加载技能并引导选择。入口集中呈现执行主链路，参数、结果结构与统计分支按需阅读，避免每次加载完整细则。

## 文档契约

| 资源 | 职责 |
|---|---|
| SKILL.md description | 表格字段相关性、两列关系及组间差异的使用场景；缺输入时先补齐；CSV/Excel 范围和因果/预测边界 |
| SKILL.md 正文 | 实际资源路径、执行入口、选择/确认/坐标、统计解释底线、完整发布与用户交付 |
| references/selection-workflow.md | 既有选择状态与交互协议，保持原文 |
| references/analysis-contract.md | 从原入口迁出 CLI 参数、结果字段与解释口径、输出文件、错误处理和交付核对 |
| references/statistical-guide.md | 从原入口迁出方法矩阵、类型推断和统计适用限制 |
| references/report-workflow.md | 既有报告阅读、展示、分享及维护规则，保持原文 |

入口在对应步骤说明何时读取参考文件；不要求无条件加载全部 references。原有数字分类/有序、共同样本、请求校正、全部方法可见、首处双语、显示精度和发布身份等要求必须保留或有清晰去向。

## 主链路

1. 请求匹配描述 → 加载短入口 → 选择协议补齐缺失输入 → 摘要与轴确认 → 原始 analysis_args 执行。
2. 成功发布 → 按结果契约读取全部方法与校正结论 → 需要时查询统计细则 → 按报告指引交付。

## Feature Task

- [x] T1 — 交付使用场景明确且按需展开的技能指引，使字段相关性请求有明确入口，主文减负并保留完整执行与解释语义。

## 验收锚点

- 描述包含用户实际请求与缺输入时的加载语义，人工检查代表性适用/不适用场景；不声称完成未执行的宿主路由实验。
- 主文相对原 243 行、25,572 字节显著缩短；关键规则逐项有去向，原参数、结果与统计分支完整保留。
- skill 校验、链接/锚点、范围与一轮 diff 审查通过，运行代码和既有测试 SHA256 不变。
- 既有选择回归与文档 CLI 实际执行通过；新包包含全部引用资源，可独立解包执行。

## 完成证据

- S24：description 明确列出“分析数据表格的字段相关性”“做相关性分析”“看看这两列有没有关系”，说明缺少文件或字段仍使用技能引导选择，保留两字段、CSV/Excel 及观察性分析边界。12 个代表性场景完成人工适用性检查，未声明宿主模型实测触发成功。
- 主入口从 243 行、25,572 字节缩减为 37 行、5,472 字节，字节减少 78.6%。七组技术契约原文迁入 analysis-contract.md/statistical-guide.md；原选择与报告指引不变，入口在对应步骤说明读取时机。见 [语义覆盖记录](../../evidence/dasci-relationship/skill-discovery-guidance/semantic-coverage.json)。
- skill quick_validate、当前链接/尾空格、CLI 参数默认值、运行/模板/测试源 SHA256 与允许范围核验通过；27 项选择回归全部通过，无失败或跳过。当前运行实现未改动，不重跑无关全量回归。
- 新包包含 18 个运行资源及全部 4 份 references，逐字节验证；独立解包后实际执行缺文件/字段、换轴重确认、完整输入直达、名称选列 CLI、有序顺序/方法子集/禁图分支，均完整发布报告；双向原始统计相同。见 [调用验证](../../evidence/dasci-relationship/skill-discovery-guidance/documented-flow.json) 与 [资源包清单](../../evidence/dasci-relationship/skill-discovery-guidance/package-manifest.json)。
- 一轮本切片 diff 审查无阻塞问题。外部安装未更新，未做真实宿主自动路由验收；YAML 与文档校验不代表已安装或必然自动触发。
- 完整证据：[acceptance.json](../../evidence/dasci-relationship/skill-discovery-guidance/acceptance.json)。T1 与 Feature 完成，Backlog 已完成，工作台 WIP=0。
