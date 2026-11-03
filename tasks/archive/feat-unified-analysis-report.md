# Feature：统一分析报告

- 标识：`unified-analysis-report`
- 状态：已完成；T1–T3 依次验收，固定模板与默认双格式报告已交付，无旧报告接口兼容层。
- 适用对象：需要在浏览器阅读、向他人分享并用 Markdown 留存分析结果的用户。
- 共享契约：[多方法统计分析](feat-relationship-statistics-coverage.md) 的 AnalysisResult、MethodResult 和校正/对照契约；来源字段沿用[选择体验](feat-table-selection-experience.md) 的精确 sheet/列标识。

## Non-Goals

- 不建设报告服务器、在线编辑器、仪表盘或托管分享服务，不新增 PDF/Word 导出。
- 不增加统计方法，不在渲染阶段重新计算统计量或让模型自行补数字。
- 不引入 CDN、外部字体、在线 JS 或通用 Markdown 执行插件；不为 HTML 输出要求网络连接。
- 不要求删除图表和机器结果；它们保留为报告配套资源，不再作为另一个独立主交付物。
- 不提供逐报告主题定制、自动换肤或根据数据临时设计页面；本 Feature 交付一个固定默认模板。

## 业务意图与现状

让多方法结论、对照证据、图表和限制构成一份完整报告：HTML 便于阅读和分享，Markdown 便于保存与后续编辑；两者表达同一分析结果，用户无需逐个打开方法报告再自行比较。
每次使用 skill 均由同一版本 HTML 模板渲染，统一章节、版式、配色、排版、表格和图表风格；数据及方法改变时，视觉规则保持一致。

实施前，`write_report` 已在 Markdown 中相对引用图像，但缺少 HTML 与同源渲染契约，最终回复仍分别引导报告和图。现已由统一 ReportModel、固定模板和双格式渲染替换旧实现，图像进入报告正文。

## 核心数据与产物契约

| 对象 | 字段及语义 |
|---|---|
| ReportModel | `schema_version`、`report_id`、`generated_at`、`html_template`、`source`、`columns`、`summary`、`method_plan`、`methods`、`tests`、`effects`、`multiplicity`、`conclusions`、`comparisons`、`tables`、`figures`、`assumptions`、`warnings`；引用同一次 AnalysisResult |
| ReportTemplate | `id: data-relationship-report`、`version: 1.0.0`；随 skill 分发的固定 HTML 骨架、组件样式及共享视觉参数；由渲染器选择，不接受数据内容指定模板或 CSS |
| Figure | `id`、`method_ids`、`question`、`title`、`caption`、`alt`、`asset_path` 或 null、`status: available/disabled/unavailable`、`reason`；标明图像对应的问题及方法，可由多个方法共享 |
| ReportPaths | `report_html_path`、`report_md_path`、`chart_paths[]`（全部实际成功图像的去重路径）、`result_path`、`out_dir` |

`ReportModel` 是内部渲染契约，无须额外输出独立文件；所有原始/校正数值和比较解释来自 AnalysisResult，格式化使用共享逻辑。
所有候选方法及其状态均进入报告，按统一多方法契约完整展示；效应量和检验分别展示，保留原假设与适用范围。

| 文件 | 最终行为 |
|---|---|
| `report.html` | 默认主阅读入口，使用随附统一模板；UTF-8，含完整正文、指标、图表和说明；图像以 data URI 内嵌，模板 CSS 内联，单文件复制后核心报告仍可离线阅读 |
| `report.md` | 与 HTML 同源的完整保存版，正文内嵌 Markdown 图片引用；图片路径相对于报告文件，复制报告目录后可读 |
| `charts/*.png` | 按分析问题命名和保存图像；方法可共享同一散点图/箱线图，不为每种方法重复画相同图；各图通过 method_ids 关联正文 |
| `result.json` | 保留完整机器结果并增加 ReportPaths、`report_template: {id, version}`；模板元数据由渲染器写入，不影响统计计算 |
| 现有 CSV 附件 | 列联表、期望频数、分组摘要、日期筛选明细等仍按方法输出；HTML/Markdown 都列明用途和位置 |

HTML 单文件分享保证核心报告正文与图表可读，不承诺附属 CSV 一并内嵌；复制整个输出目录才包含完整复查附件。Markdown 交付单位为 `report.md` 及其相对资源，不能声称单独复制 md 文件也保有图像。

## 统一 HTML 模板与视觉契约

- skill 的 assets 中维护唯一默认模板及共享视觉参数，纳入版本管理并随 skill 分发；所有分析分支通过同一渲染入口填充 ReportModel，不在运行时由模型重写页面骨架、CSS 或另选主题。
- 模板仅接收已转义的文本、统计结果及预定义表格/图片组件。动态内容包括来源、字段、解释、方法行、图像和附件；布局、组件类名、间距和配色由模板负责。
- 固定结构为：页头 → 摘要 → 来源与清理 → 方法计划 → 对照表 → 图表 → 方法明细 → 差异解释 → 假设与限制 → 附件与复现信息。各区有稳定锚点，导航顺序一致。
- 没有图、没有有效推断或某方法不适用时，使用对应区域的统一状态/空态组件并说明原因；不删除主要区域或临时重排页面。方法与图表数量变化只增减区内条目。

| 视觉项目 | 初始默认模板的固定规则 |
|---|---|
| 页面与布局 | 固定浅色主题，页面底色 `#F5F7FB`、白色内容面板；内容最大宽 1200px，居中；窄屏按同一断点规则堆叠，长表在容器内横向滚动 |
| 颜色 | 主色 `#2563EB`，正文 `#1F2937`，次级文字 `#64748B`，边框 `#E2E8F0`；注意事项使用琥珀色与文字提示，不用颜色代替结论 |
| 排版 | 系统无衬线字体，中文依次使用可用的微软雅黑/PingFang SC/Noto Sans CJK SC；正文 16px、行高 1.65，标题层级固定；表格数字右对齐并使用等宽数字特性 |
| 组件 | 8px 基础间距、12px 面板圆角；统一标题、摘要卡、表格表头/单元格、图注、方法状态、注意事项和附件样式，组件不因数据集而另行设计 |
| 摘要卡 | 固定展示有效配对 N、已计算方法数、有效检验数 m、alpha；已计算方法数不包含 not_applicable，描述性计算可计入；不因某次结果显著而换成突出最大效应的卡片 |
| 图表 | 散点图、箱线图、热图和时间图共用字体族、固定调色板、轴/网格/图例/标题规范及图注样式；同一报告相同类别颜色一致，ordinal 顺序仍由用户定义 |
| 状态语义 | 已计算、仅描述、不适用、图不可用均有固定文字标签和样式；显著与否不映射成“成功/失败”，正负相关不映射成“好/坏” |

页面 CSS 与图表绘制读取同一套视觉参数；新图表类型沿用这些参数。正文和栅格图可按同一约定字体族选用本机可用字体，中文可读性继续按下文验收。
同一模板版本在相同字体/浏览器/视口下保持相同视觉规则；跨系统验收版式、组件与参数，不要求字体栅格化逐像素相同。
HTML 根节点记录 `data-template-id`、`data-template-version`，页脚标记模板版本，并与 result.json 一致；统计数据与模板版本分开管理。
改动骨架、组件或共享视觉参数时更新模板版本并重验基准样例；分析请求不能临时改版本、CSS 或组件顺序。
渲染时把模板样式与图像资源内联到最终 HTML，不依赖源模板路径；模板缺失或必需槽位无法绑定时报告生成失败，不由模型临时补写另一种页面。

## 报告内容与展示契约

顺序统一为：按问题组织的结论摘要 → 数据来源与样本清理 → 方法计划与理由 → 多方法对照表 → 关系图及图注 → 方法明细 → 结果差异、假设与限制 → 附件及复现信息。

- 摘要包含字段、有效样本量、实际适用方法、各问题的校正后证据和限制；没有可用推断时明确只作描述。方法结果不同则说明差异，不压缩成未经定义的单一“有关/无关”。
- 数据来源列出文件、精确 sheet、字段编号/名称、有效类型、ordinal/二分类映射、清理排除数、转换单位；原始数据行不全量复制到报告。
- 多方法对照表逐项列出“方法、分析问题、N、统计量、适用的 df、原始 p、Holm 校正 p、效应量、适用的单项 CI、状态/原因”；日历方法列出叶子明细，不给方法容器编造 p。
- 报告列明校正 family、有效检验数 m、alpha；结论统一引用请求级 Holm。不同量纲的 r/V/η² 不放在同一强度排名中。
- 差异说明直接呈现 comparisons/conclusions：哪些问题有证据、哪些证据不足、哪些方法回答不同问题；不按多数票、最小原始 p 或旧主方法裁决。模型补充的可能解释必须标明未经验证。
- 关系图放在对应分析正文，配合说明“这张图如何对应结论”；每个适用方法有相关图或共享图映射，图与统计量一致，无须按方法数量重复相同图。
- 列联表截断/合并、散点图抽样及分组图裁剪都注明展示范围、总范围和“统计使用完整配对数据”；完整明细继续由附件提供。
- ordinal 图表保留用户顺序及原等级标签，不能按字符串顺序重排，也不能在图中暗示未经确认的数量间距；日期轴显示可理解的日期与单位。
- 中文正文、字段名、图注应可读；测试发现当前图像字体无法显示中文时必须解决可用字体或使用可读替代标注并保留原名映射，不能把乱码作为正常交付。
- HTML 标题、表格、目录导航和图片按统一模板适应普通桌面与窄屏；表格可横向滚动。读取报告无需启动 Python 或服务。
- 文件、sheet、列名及单元格内容均按文本转义，不能作为 HTML/Markdown 代码执行；普通文本中的 `<script>`、`&`、管道和换行不会破坏报告结构。

## 失败与最终回复

- 默认同一次 `analyze` 必须生成 HTML 和 Markdown；不增加必须手动开启的格式参数。保留 `--out` 与 `--no-chart` 的意义。
- `--no-chart` 或预期的绘图依赖/字体失败时，两份正文保留全部方法结果，统一显示未生成图像的原因，不留损坏引用；`chart_paths` 只含实际成功图像，无图时为空数组。未知统计/内部错误仍应失败。
- 任一必需报告写入失败时 `ok=false`，说明失败产物，不宣称全部成功；图表不可用属于允许降级，但不免除双格式报告要求。
- 最终回复提供一句核心结论、HTML 展示入口和 Markdown 保存入口；宿主支持 `present` 或预览时展示 HTML，否则提供可打开路径。配套图和 CSV 归入附件说明，不再让用户先拼接报告与图。
- 仅使用 `report_html_path/report_md_path/chart_paths` 定位报告与图像，不提供旧 `report_path/chart_path` 别名；HTML 内嵌全部可用图，Markdown 的所有图使用相对路径。

## 主链路

1. 多方法分析与校正完成 → 形成唯一 ReportModel → 用共享视觉参数生成/复用图像 → 固定模板填充 HTML、同源渲染 Markdown → 内联 HTML 资源并记录模板版本 → 写 result.json → 回复两个报告入口。
2. 用户禁图或预期绘图失败 → Figure 标记状态与原因 → 双格式输出一致的无图说明；必需报告失败 → 命令失败并报告具体文件。

## Feature Task

- [x] T1 — 交付统一的多方法报告结构和对照解释，使全部方法、校正证据、图表和限制从同一结果生成并可追溯。
- [x] T2 — 交付固定版本模板驱动的 HTML 展示版、统一图表风格与同源 Markdown 保存版，使跨次报告视觉一致且按各自资源边界离线分享。
- [x] T3 — 交付双格式输出流程与无图降级，并通过跨统计分支的内容及视觉回归，使报告缺失、风格漂移和生成失败不会被误报为成功。

## 验收锚点与执行入口

以下 C1–C10 已全部验收，自动测试、实际渲染与截图记录见完成证据。

| 用例 | 机器断言或可复现浏览器断言 |
|---|---|
| C1 同源 | 用固定多方法 AnalysisResult 渲染两格式，解析比对来源、列语义、N、每种方法状态、原始/校正 p、效应量、CI、校正 family/m、对照解释、图注和警告，与输入一致 |
| C2 统计分支 | 覆盖 Pearson/Spearman/Kendall、点二列/Welch t/U、ANOVA/Welch ANOVA/KW、卡方/Fisher/G/置换与日期筛选；方法集完整，ordinal 顺序、编码方向与日期单位保留 |
| C3 离线资源 | HTML 的图像 data URI 可解码为有效图；无远程资源请求；把单个 HTML 复制到另一目录后图文可读；Markdown 图片可相对定位，复制目录后仍有效 |
| C4 错误与转义 | `--no-chart`、模拟 Pillow 不可用、必需报告路径不可写；前两项双格式成功且无坏链，后一项失败；中文/空格/HTML 片段/管道/换行输入被正确转义 |
| C5 产物 | HTML/Markdown 两个路径均存在且可读，chart_paths 只含成功图像；result.json 和 CSV 可读；默认 CLI 一次生成两格式；摘要不编造缺失指标 |
| C6 实际阅读 | 浏览器离线打开桌面/窄屏报告和复制后的 HTML，检查中文可读、图注/表格完整、无裁切遮挡；用 Markdown 阅读器打开完整输出目录检查图文 |
| C7 多方法对照 | 一致、方向/证据不同、只有一种可用、全部仅描述四种结果均保留完整清单；原始显著而校正不显著不会误报；不同量纲不排名，派生效应与校准变体不重复计票 |
| C8 多图映射 | 相关方法共享散点图，分组和日历方法分别关联适当图；同一资源去重，无图时 chart_paths 为空；部分图像失败的状态可辨认，HTML/Markdown 均无坏链 |
| C9 模板复用 | 数值、分类、混合、日期、无图五类固定结果均通过同一模板；根节点/JSON 的 id/version 一致；同版本内联 CSS、主要区块顺序和组件规范一致，动态内容正确替换；图表使用共享参数；模板缺失/槽位未绑定时明确失败 |
| C10 视觉一致 | 同一浏览器/字体环境下，五类基准报告在 1440px 与 390px 视口保留统一配色、标题层级、面板、表格、图注和状态风格；实际图表遵循主题，长标题/大表/无图不破坏版式；布局改动必须复验并更新模板版本 |

自动入口：`python3 -m unittest discover -s tests/dasci-relationship -p 'test_report_*.py'`，覆盖 C1–C5/C7–C9；同时执行统计 A2/A6–A9 和选择 B3 回归，覆盖多方法、校正及共享契约。

C6/C10 在实施工作台冻结浏览器、字体、Markdown 阅读器、基准样例和断言后执行，保存同环境截图供视觉核对；至少涵盖中文、长列名、大表截断和无图。
验收须实际渲染报告并核对布局、计算样式及图像，不以模板字符串存在、版本字段相等或文件生成成功替代视觉检查。最后运行 skill-creator 的 `scripts/quick_validate.py skills/dasci-relationship`。

## 完成证据

### S12 / T1

- 2026-11-02，同源 ReportModel 与固定展示树已交付，深拷贝全部多方法/叶子检验/效应/校正/对照信息，不调用统计入口；来源、清理、类型与编码可追溯。
- 图映射保留 ordinal 顺序与标签，相关方法共享图，时间位置与日历叶子分图；表格裁剪注明完整范围及 CSV。
- 新增 7 项模型测试（包含全部 15 类型组合）及统计回归 97 项：selected=executed=passed=104，failed=skipped=not_executed=0。语法、skill、范围/尾空格检查及一轮基线 diff 审查通过。
- 证据 evidence/dasci-relationship/unified-analysis-report/t1/，本地缓存未入库；无有效 Git 元数据，以原文/SHA256 基线审查。T1 已验收；T2/T3 待实施，按用户授权继续。

### S13 / T2

- 2026-11-02，唯一默认 HTML 骨架/样式与 theme.json 已交付，模板 data-relationship-report / 1.0.0；HTML/图表共享字体/配色/网格，ordinal 顺序不按样本数重排，同标签跨图颜色一致。
- 双格式渲染器共用报告树与格式化逻辑，HTML 图像内嵌 PNG data URI、CSS 内联；Markdown 使用 charts/ 相对资源。全部主要章节/状态保留，文本分别转义，不执行外部内容。
- 禁图、Pillow/字体不可用及部分图失败保留正文/原因；未知内部绘图异常传播。模板缺失/槽位不全明确失败。
- 15 项报告测试（T1 7 + T2 8）与统计97项：selected=executed=passed=112，failed=skipped=not_executed=0；语法、skill、范围/尾空格及一轮diff审查通过。证据 evidence/dasci-relationship/unified-analysis-report/t2/，未入库。
- T2 已验收；CLI默认双格式、旧接口移除及真实浏览器/Markdown阅读验收在T3实施，不将本切片资源断言视为视觉验收。

### S14 / T3 与 Feature 完整验收

- 2026-11-02 UTC，默认 analyze 一次生成 report.html/report.md、按问题命名的 charts/、适用 CSV 与 result.json；同源正文保留全部候选、叶子统计量、原始/Holm p、效应/单项 CI、类型编码、共同 N、方法差异和限制。固定模板 data-relationship-report / 1.0.0。
- 删除旧 write_report/md_table/_display_table/_render_chart 与 report_path/chart_path，统一输出 report_html_path/report_md_path/chart_paths/result_path/out_dir/report_template；figures 保留逐图状态、原因及方法映射。没有适配器/旧字段别名或新增运行依赖。
- --no-chart、Pillow/中文字体不可用和单图失败保留双报告；未知内部异常失败。必需 HTML/Markdown、CSV、机器结果写入失败附具体文件并返回失败；重跑前移除旧 result.json 成功标记。
- C1/C2/C5：全部 15 类型组合经实际分析核对 HTML 与 Markdown 阅读渲染后的逐表内容、精确原始/校正数值与机器结果；真实 CLI 进程验证默认双格式。C4 覆盖文字转义、各必需报告不可写、模板缺失、禁图/缺依赖与未知绘图错误。
- C7：固定结果包含一致、方向相反、原始显著但 Holm 不拒绝、显式单方法、仅一个方法可推断、全部仅描述；保留真实方法列表/状态与引用。C8：共享相关图、时间位置与日历多图、部分失败与路径去重均验证。C9：同模板/CSS、data URI、必要槽位失败及共享主题均验证。
- 自动验收：报告 23 项（T1 7 + T2 8 + T3 8）、统计 97 项、选择 27 项，selected=executed=passed=147，failed=skipped=not_executed=0；全部 Python 语法、skill quick_validate、范围/尾空格及一轮本切片 diff 审查通过。
- C3/C6/C10：Google Chrome for Testing 148.0.7778.96、Microsoft YaHei、本地 file://，数值/分类大表/混合/日期/无图五份真实 CLI 报告分别在 1440×1000、390×844 验证计算样式/章节/导航/摘要卡/页面宽度/图像；10 个布局用例通过。复制到隔离目录的单 HTML 核心图文离线可读；markdown-it-py 3.0.0 commonmark+table 的五份阅读副本均检查真实图像/中文/表格；远程资源请求为零。
- 已查看五类桌面/窄屏截图汇总及长中文、热图、箱线、时间、无图、Markdown 代表截图。长热图列改用 C1/C2 标记，图注保留原标签映射；大表横向滚动，未出现页面横向溢出。视觉保证限于已验收浏览器/字体环境，不声称跨系统像素一致。
- 本地未入库证据 evidence/dasci-relationship/unified-analysis-report/t3/：acceptance.json、visual/acceptance.json、visual/*.png、visual/*/report.html/report.md/result.json、changes.diff、review.log、finalization.json；浏览器启动的沙箱 socket 限制经沙箱外本地离线验收解决。
- methods/stats/inference/selection/interaction 文件与 Feature 起点 SHA256 一致；data_relationship 的准备/计算/选择定义不变，仅报告编排修改及旧报告定义删除。最终源码/资源/测试哈希与完整验收记录一致。
- T1–T3 全部完成，Feature 已归档，backlog 完成，WIP=0；无提交/推送。现场无有效 Git 元数据，以新建原文/SHA256 基线完成范围与 diff 审查。
