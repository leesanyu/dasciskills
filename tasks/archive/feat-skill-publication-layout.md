# Feature：dasci 技能命名与发布目录

- 标识：`skill-publication-layout`
- 状态：已完成并归档。
- 适用对象：维护、测试和发布数据科学技能系列的开发者。

## Non-Goals

- 不改变统计、选择、绘图、报告的行为和公共调用参数，不升级 Python 依赖。
- 不更新外部 Harness 安装，不重新生成历史报告或改写历史证据，不提交或推送。

## 业务意图

将关系分析技能统一命名为 `dasci-relationship`，以 dasci 表示 data science，供后续同系列技能沿用前缀。运行资源、开发测试和验收证据分别管理，发布时能直接取得干净的技能目录，测试仍能定位正确源码。

## 目录契约

```text
skills/
└── dasci-relationship/
    ├── SKILL.md
    ├── scripts/
    ├── assets/
    └── references/
tests/
└── dasci-relationship/
    ├── test_*.py
    ├── report_visual_check.py
    └── fixtures/
evidence/
└── dasci-relationship/
    └── 原 evidence 内容及后续本技能证据
```

- `SKILL.md` 的 `name` 为 `dasci-relationship`，目录名一致；脚本文件名、模块名、运行接口不变。
- 测试通过自身文件位置定位仓库根和 `skills/dasci-relationship/scripts`，不依赖当前工作目录；fixtures 随测试迁移。
- 已有证据逐文件移动且 SHA256 不变，其中旧运行路径、旧版本和旧归档名作为历史事实保留；当前维护文档更新为新的证据入口。
- 新发布包的唯一顶层目录为 `dasci-relationship/`，只包含 16 个运行资源，排除测试、证据和缓存；不提供旧名称兼容入口。

## 主链路

1. 开发验证：新测试目录 → 定位新技能目录 → 原有完整测试与 CLI 运行 → 证据进入对应技能目录。
2. 发布验证：技能新目录 → 打包运行资源 → 独立解包 → select/换轴/确认/analyze → 完整报告发布。

## Feature Task

- [x] T1 — 交付按技能名称分区的源码、测试和证据布局，使 dasci-relationship 可独立发布且迁移后测试、命令和证据入口可用。

## 验收锚点

- 根目录不再存在旧技能目录；测试不在发布目录中，全部原测试和 fixtures 位于新测试目录。
- 从仓库外执行新 discover 路径，全部既有测试通过；Python 语法、skill quick_validate、当前文档入口检查通过。
- 全部 759 个历史证据文件移动后哈希与迁移前完全相同；运行算法和模板未改动。
- 新包资源与源码逐字节相同，独立解包能选择和调整坐标，并实际发布 HTML/Markdown/JSON/PNG。

## 完成证据

- S23：技能 frontmatter 已改为 `dasci-relationship`；运行目录、14 个测试/视觉入口与 fixtures、全部原始证据迁移完成，旧根目录不再存在。当前维护命令、技能说明与证据链接已同步。
- 完整技能回归从 `/tmp` 发现新测试目录，183 项全部执行通过，无失败或跳过。新入口为 `python3 -B -m unittest discover -s tests/dasci-relationship -p 'test_*.py' -v`；Python 语法、skill quick_validate 和本地文档链接检查通过。
- 全部 759 个历史证据文件迁移后 SHA256 与原文件完全一致，未重写历史 JSON、报告、快照或旧包。运行算法和模板不变，`stats.py` 仅改技能名称说明；见 [迁移清单](../../evidence/dasci-relationship/skill-publication-layout/migration-manifest.json)。
- 新包 `dasci-relationship-1.4.0.zip` 含 16 个运行资源，无测试、证据或缓存，逐字节核验通过；从仓库外独立解包后，真实 inspect、select、换轴确认和 analyze 完整发布 HTML/Markdown/JSON/PNG 均通过。见 [资源包清单](../../evidence/dasci-relationship/skill-publication-layout/package-manifest.json)。
- 一轮本次 diff 审查与冻结范围检查通过。当前无 Git 元数据，使用 SHA256 与明确迁移映射核对，未初始化 Git。未更新外部 Harness 安装；本轮不改视觉布局，仅核验视觉脚本新路径可启动。
- 完整记录见 [验收证据](../../evidence/dasci-relationship/skill-publication-layout/acceptance.json)。T1 与 Feature 完成，Backlog 已标记完成，工作台 WIP=0。
