# Feature：字段选择与绘图方向合并

- 标识：ordered-field-picker
- 状态：进行中且检查点通过；用户已确认 DeepSeek Harness 字段选择可用；S29 修正 WorkBuddy 将 sendPrompt 误当独立工具的路由，自动化、实际宿主桥接与独立包通过，WorkBuddy 新控件真实 UI 待验收。
- 适用对象：在技能中选择两字段并指定绘图方向的用户。

## Non-Goals

不修改宿主 UI，不更改统计/绘图/报告算法，不增加运行依赖，不同步外部安装。

## 业务意图

用户在当前对话中从完整字段列表选择 X/Y 并提交。支持完整原生选项时用两个单选问题；WorkBuddy 的普通提问有 2–4 项硬上限，使用其真实 show_widget/sendPrompt 能力呈现可滚动、搜索、交换的对话内控件。无控件且原生受限时列完整目录，直接回复 X → Y。无需后置换轴或外部页面，不修改宿主软件。

## 核心契约

- action.pair：{x: {name/index, type?, order?}, y: 同结构}，与 columns/plot_x 互斥；未提交的默认值无效。
- 字段身份稳定，反向选择只改变绘图方向；合法完整提交直接 ready，无再次组合确认。业务语义不足仍补齐，不推测有序水平。
- 全部字段按物理编号呈现；预览每页 20 项不限制候选，只有显式搜索才过滤。不可选字段保留原因，合法类型覆盖保留；不挑常用项、重排或合并字段。
- 原生 question.mode=tool，questions 以 x/y 标识两题，tool_arguments 可直接用于已核对的 DeepSeek Harness schema；选项完整且不按答案数组顺序推断轴。
- host.max_options 仅填写工具明确声明的硬上限，省略时不裁剪。host.inline_widget=true 仅用于真实的对话内 HTML/JS 与 sendPrompt 能力，返回 mode=widget 及完整 show_widget 参数；无此能力且原生受限时用完整目录和有序文字。
- host.tools:string[] 传当前真实工具名；同时有 widget_guidelines/show_widget 时直接返回 mode=widget，不因 questions=false 或 inline_widget=false 改用文字。sendPrompt 是控件运行环境注入的 JavaScript 函数，不是智能体工具；实际显示 show_widget 后才能等待用户操作。
- 控件两侧完整滚动列表、搜索与交换，开始按钮才提交 pair/context_key；无预选、取消不分析。context_key 绑定路径/sheet/size/mtime，文件或工作表变化时拒绝旧提交。回传少于 500 字，不携带原始值/完整路径；不用本地端口、不增加依赖。
- 可选网页入口仍用 loopback 临时页与随机会话路径，取消/超时不分析，源文件变更使旧提交失效。

## 主链路

1. 缺字段 → 全部原生 X/Y 选项，或对话内完整滚动控件 → 明确提交 pair（控件附 context_key）→ ready → 按返回参数执行并核验完整发布。
2. 无控件且原生受限 → 完整编号目录 → 对话内回复 A → B → action.pair → ready；缺业务语义则只补齐缺项，源数据变化则重选。

## Feature Task

- [ ] T1 — 交付当前对话内的字段与坐标一次选择，使两个宿主都能明确提交 X/Y、无需额外网页且结果图与选择一致。

## 验收锚点

完整候选与一次提交；13/65 列不受预览分页限制；控件搜索/交换/取消/不可选原因/消息长度；原生 schema 与实际 WorkBuddy 控件校验；文件/sheet 变化拒绝旧提交；稳定统计输入；选择与绘图回归；独立发布包与文档校验。真实宿主加载、点击和滚动须单独验收，不能用 Node DOM 模拟或静态 schema 替代。具体命令与文件范围冻结在工作台。

## 完成证据

- S25 已实现同页 X → Y 字段选择与箭头交换，pair 一次提交直接 ready；文字入口支持有序输入，必要业务语义仍须补齐。旧确认菜单已去除后置换轴项。
- 62 项自动化全部通过（选择 27、绘图 23、新选择器 12），无失败/跳过；技能、语法、链接、源码范围和单轮审查通过，未增加运行依赖。
- 独立包含 20 个运行资源，逐字节匹配源码；解包后实际 select 与两方向分析均完整发布，图与摘要方向一致，原始统计相同。见 [验收记录](../../evidence/dasci-relationship/ordered-field-picker/acceptance.json)。
- [交互预览](../../evidence/dasci-relationship/ordered-field-picker/field-picker-preview.html) 可查看选择/交换；它不运行分析。HTTP 内存测试与 Node DOM 事件测试不代表真实浏览器验收。
- S25 时 sandbox 拒绝 socket 创建，Chromium crashpad 亦被 socket 权限拒绝；可选网页的真实监听/浏览器验收尚未通过，[实测脚本](../../evidence/dasci-relationship/ordered-field-picker/verify_live_picker.py) 已准备。这不代表默认原生提问流程的验收结果。
- S27 已交付默认对话内两题单选，只有单题或选项受限时仍在对话内收集明确方向；网页仅用户主动请求时使用。71 项自动化全部通过，20 运行资源独立包实际选择/两方向分析完整发布且统计一致；见 [验收记录](../../evidence/dasci-relationship/native-field-selection/acceptance.json)。
- 两个宿主的真实原生提问尚未实测，实际加载路径未确认；外部副本未同步。T1 保持未完成、规格不归档，工作台 WIP=0。
- S28 已核对截图对应 WorkBuddy 提问与 2–4 选项硬上限；DeepSeek Harness schema 无声明选项上限。改为全字段原生参数及 WorkBuddy 对话内滚动控件，80 项测试通过（宿主13、控件5、选择27、绘图23、可选网页12），无失败/跳过。
- 22 运行资源独立包逐字节匹配；13/65 字段完整选项通过实际 DSH schema、控件通过当前 WorkBuddy 入参校验；解包后的两方向分析均完整发布且原始统计相同。见 [S28 验收记录](../../evidence/dasci-relationship/complete-field-options/acceptance.json)。
- S28 尚未在真实宿主 UI 中加载/点击/滚动验收，外部安装未覆盖；T1 保持未完成。
- S29 用户确认 DeepSeek Harness 已可用；WorkBuddy 会话已读取全部新版资源，但因 sendPrompt 不在工具列表而自行选择 host.questions=false，未调用控件，截图步骤实际在等待文字答复。已修正技能指引和 tools 路由，另有 Skill 注册错误仅隔离记录。
- S29 的 83 项测试通过（宿主16、控件5、选择27、绘图23、可选网页12），无失败/跳过。实际安装版 show_widget handler、renderer sendPrompt 桥接及模板事件在 Node VM 中联测，13/65 完整字段回传均通过；独立 22 资源包实际两方向报告完整发布且统计一致。见 [S29 验收记录](../../evidence/dasci-relationship/workbuddy-widget-routing/acceptance.json)。
- WorkBuddy 外部安装未覆盖，新版真实 UI 仍待加载/点击/滚动验收；T1 保持未完成，不将 VM 测试当作 UI 验收。
