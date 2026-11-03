# 文件、工作表与字段选择

在运行用户的分析前，用 `scripts/data_relationship.py select --request <临时JSON路径>` 推进选择。宿主模型维护返回的 `state`，将用户本轮回答转换为 `action`。这是模型内部调用协议；用户只需给文件、名称/编号和自然语言业务顺序。

## 请求与返回

首次完整输入示例（Excel 额外提供 `sheet`）：

```json
{
  "action": {
    "input": "/workspace/销售.csv",
    "pair": {"x": {"name": "销售额"}, "y": {"name": "利润"}},
    "methods": "auto"
  },
  "host": {"questions": true, "max_questions": 2}
}
```

`host` 填本会话实际工具能力：`tools` 是当前确实提供的工具名数组，同时包含 `widget_guidelines` 和 `show_widget` 时脚本自动生成对话内控件，不受 questions/inline_widget=false 影响。`sendPrompt` 是控件内部注入的 JavaScript 函数，不是独立工具，不能用“工具列表没有 sendPrompt”判断控件不可用。其他宿主仍可显式传 inline_widget=true，默认 false。

`questions` 表示有提问工具，`max_questions` 是一次调用的问题上限（默认 2）。`max_options` 仅在 schema 明确声明每题硬上限时填写，省略表示不裁剪；不要猜成 4 或 20。tools 不推测原生上限。`multi_select` 不保证点击顺序，也不是 X/Y 选择的前提。

## 在当前对话中选择字段与方向

在当前对话中完成选择，**不打开额外页面**。候选来自全部字段，不受预览每页 20 项影响；只有显式 search 才过滤。按原物理编号列出，禁止挑常用项、重排、合并独热字段或把未显示字段堆到题干中。

### 原生提问：DeepSeek Harness

当前已核对的 ask_user_question schema 没有选项数上限，不自行添加 max_options。`question.mode=tool` 且 `tool_arguments` 非 null 时，它已包含 questions 两题的 id/header/question/options/multi_select，可直接用于这个 schema；其他宿主按实际 schema 调整键名，保留所有选项及编号。不要把整个 question 当工具参数。

同一次调用分别询问 X/Y，每题单选。按 id=x/y 关联答案；宿主以 header 或问题原文关联时保留该映射，不按答案数组顺序绑定坐标。选项 label 中的 #编号对应 questions.options.value.index。默认高亮、部分答案或等待中的提问不能触发分析。

### 对话内滚动控件：WorkBuddy

已核对版本的 AskUserQuestion 每题要求 2–4 项。当前会话有 `widget_guidelines` 和 `show_widget` 时，直接使用对话内控件；**sendPrompt 不需要出现在工具列表中**。它由 WorkBuddy 的控件运行环境注入为 `window.sendPrompt(text)`，发送消息回当前对话，已在安装版本中核对桥接实现。

1. 按宿主实际 schema 调用 `widget_guidelines`，读取 interactive 指引（已核对版本为 `modules:["interactive"]`）。
2. 调用 select，host 使用下例，不把 questions=false 当作禁用控件，也不因不确定 sendPrompt 而省略 tools：

   ```json
   {"action":{"input":"用户指定路径"},"host":{"tools":["widget_guidelines","show_widget"]}}
   ```

3. 将返回的 `question.widget` **原样**作为 show_widget 参数：title、widget_code、loading_messages。widget_code 是含数据的完整 HTML 片段，不能重写成四项菜单、截取字段或另开本地服务。完成 select 尚未显示控件，必须实际调用 show_widget，才能结束本轮等待用户选择。
4. 等待用户在对话内控件中操作。两侧各有全部字段、滚动条、搜索与交换按钮；不可选字段显示原因。控件生成成功不代表用户已经选择。只有这两个工具确实缺失或实际调用报错时，才解释具体原因并使用下述文字方式；未尝试调用不能声称控件不支持。
5. 仅点击“开始分析”会通过 sendPrompt 发回短 JSON，例如 `{"pair":{"x":{"index":7},"y":{"index":2}},"context_key":"…"}`。将 pair/context_key 原样放入 action，并携带本控件对应的完整 state 再调用 select。不要运行旧 analysis_args。取消不提交、不分析。

context_key 绑定文件路径、工作表、文件大小和修改时间；文件变化后旧控件不能提交，脚本返回 needs_columns，使用新 widget 重新选择。回传消息仅含编号和校验键，不含数据值或完整路径；长度低于宿主 500 字限制。

### 缺少控件或工具受限

`tool_arguments=null` 时不能用它调用工具。超出原生每题上限且没有对话内控件时，使用 `question.fields` 展示完整编号目录及不可选原因，在当前对话一次收集 `#2 → #7`（左 X、右 Y）。只有单题工具时 questions 为 id=pair；若工具不能省略 options，改用普通文字。无提问工具时也用有序文字。名称含箭头或逗号时用编号。普通 Markdown 箭头不可点击，不声称有限选项菜单已有滚动能力。

例如，一次提问中 X 选择 `#7 利润`、Y 选择 `#2 销售额`，转为：

```json
{"action":{"pair":{"x":{"index":7},"y":{"index":2}}}}
```

请求同时携带上次返回的完整 state。合法且语义齐全直接 ready，不先提交无序 columns、不增加后置换轴或组合确认；同一字段重复选择时显示错误并让用户在当前对话纠正。

后续请求传回**完整 state 原值**，只在 `action` 写本轮实际提交的变更：

```json
{
  "state": {},
  "action": {"sheet": {"index": 2}},
  "view": {"page": 1},
  "host": {"questions": false}
}
```

上例的 `{}` 位置应放前次真实 `state`。不要自行设置 `confirmed` 或 `confirmation_key`。`action` 可包含：

| 字段 | 输入 |
|---|---|
| `input` | 用户指定的文件路径；不扫描猜文件 |
| `sheet` | `{"name":"精确名称"}` 或 `{"index":2}`；同时给出时必须一致；CSV 不传 |
| `pair` | `{"x":{"index":2},"y":{"index":7}}`；同一 action 明确提交字段和方向，与 columns/plot_x 互斥；支持名称、业务类型与完整 order。合法且语义齐全时直接 ready，无再次组合确认 |
| `context_key` | 对话内控件回传的原值，与 pair 同传；源文件或工作表变化后拒绝旧提交并重新选择 |
| `columns` | `{"1":{"index":2},"2":{"index":7}}`；只改一列时只传对应槽位；null 清除该槽 |
| 字段槽位的 `name/index` | 精确名称或原始物理编号；逗号/空格名称完整传入字符串，不按逗号直接拆成多个名字 |
| 字段槽位的 `type/order` | 类型默认 auto；用户确认后用 numeric/boolean/categorical/ordinal/datetime；ordinal 的 order 为完整 JSON 标量数组 |
| `plot_x` | auto（默认）/col1/col2；只指定横轴，另一字段为纵轴。用户自然语言指明 X/Y 后，按所选字段的槽位转换；不交换 columns |
| `methods` | 默认 auto；用户明确指定时转换为方法标识列表字符串，如 spearman,kendall_tau_b |
| `explicit` | 仅当前 action 明确包含文件、所需 sheet、两列，且来自用户完整指定时为 true；不把交互结果累积成一次“完整初始输入”绕过组合确认 |
| `confirm` | 用户针对已展示摘要选择“开始分析”时为 true；修改选择后先重新展示摘要 |
| `source` | 默认为 submitted；工具默认高亮或尚未提交时用 default，脚本忽略选择与确认 |

`view` 支持 `page`、`search`、`all_columns`。预览目录每页 20 项；不限制原生 options 或 widget 的完整字段列表，搜索和分页不改变原始编号。`all_columns=true` 可获取完整预览目录。第二次单选的预览会排除已选列，但呈现候选仍保留它供两种方向选择；合法的用户类型覆盖也保留。

返回包含 `step/state/question/catalog/preview/semantic_context/summary/analysis_args`。`ok=false` 表示本轮输入需纠正；继续使用返回 state，只修正该步骤。请求 JSON 无法解析或结构非法时，CLI 返回错误，修正请求本身。未知内部计算错误不得视为正常选择失败。

## 按状态呈现

- `needs_file`：只询问文件路径。已指定的合法对象不重新询问。
- `needs_sheet`：展示文件名、工作表总数、当前页/范围、编号、完整名称、约行×列、隐藏状态、可选原因。尺寸是含表头/格式的已用区域估计，null 显示“未知”，不能写成有效 N。空表不可选；隐藏表可以明确选。只有一个 sheet 也接受明确选择，不自动代选。
- `needs_columns`：按 mode 使用上面的控件、原生两题或有序文字，同时确定字段与方向。文件/sheet、行数及前 5 行预览用于核对输入，不能当作字段候选范围；控件只包含编号/名称/类型/不可选原因，不嵌入原始样例值。名称有歧义时用编号。合法字段状态保留，最终提交完整 pair。
- `needs_semantics`：使用 `semantic_context` 展示受影响字段、观察到的实际水平、推断/建议和原因。确认数字是测量值还是分类编码；有序分类要求用户给出完整业务顺序，例如“低 → 中 → 高”。只补齐缺失项，不要求用户写 JSON。方法不适用时按错误给出的适用集合重选方法，保留合法字段。
- `needs_confirmation`：仅用于原始 columns 诊断调用或补齐语义后的新摘要，展示文件/sheet、编号/名称/类型、共同 N、横纵轴和候选方法，提供“开始分析 / 修改字段”；不再提供后置换轴选项。正常 pair 提交不经过此状态。候选不保证全部可计算。
- `ready`：展示同一摘要并立即执行 `analysis_args`。完整初始输入不会再要求确认；`question=null`。可以追加用户要求的 `--out/--alpha/--seed/--permutations/--no-chart`，保持选定列、语义、顺序和方法不变。参数按数组传给进程，或使用当前 shell 的正确转义。

`mode=widget` 原样展示 widget 后等待消息；`mode=tool` 字段步骤读 tool_arguments/questions，其他步骤沿用 title/options；`mode=text` 给完整编号列表和普通文字问题。字段选择不要求多选能力；疑似 ID/空列/常量/高基数文本保留原因，不作为正常可选值。用户明确修正类型并通过校验后可选。

## 绘图方向

用户看到的顺序与统计槽位分开：pair.x 是横轴、pair.y 是纵轴。已有同一字段组合时保留统计槽位，否则按物理编号固定绑定；两方向仅 plot_x 不同，不丢失字段类型/order/方法。用户只需看 A → B，不需要知道内部槽位。pair 可以随缺文件/sheet 的状态保留待绑定意图，但这些缺口补齐后仍展示实际摘要，不能把未提交默认值当作选择。

采用 summary.plot 的实际解析值显示“横轴：完整字段名；纵轴：完整字段名”。auto 规则为：单时间散点优先时间在横轴，其他散点按槽位；箱线图数值在横轴、分组在纵轴；时间类别图时间在横轴；类别/等级热图第一字段在横轴。显式 plot_x 始终优先；按最终有效类型解析，不在语义未确定时承诺布局。

不要将工具预选值提交 pair；默认高亮不是用户意图。两轴须由用户明确表达，不代表自变量/因变量或因果。直接诊断调用仍可用 plot_x；完整初始 columns 输入未指定轴时沿用脚本默认。业务语义不足时仍须补齐，不能凭 pair 绕过有序顺序要求。

plot_x 和解析后的轴均属于确认范围；变更使旧确认失效。analysis_args 已携带相同请求，不在执行时追加冲突的 --plot-x。结果 plot 必须与摘要一致，逐图 axes 记录实际坐标；派生日历图有自己的轴。--no-chart 保留计划，不额外询问。

## 局部纠错

文件或 sheet 改变会清除原字段绑定；替换一个字段仅清理该槽旧类型/顺序，另一列保留。这些身份变更将旧 plot_x 恢复 auto，同一 action 中的新 plot_x 对更新后的字段生效；只修正类型或等级顺序时保留显式轴意图并重新解析，修改方法或翻页/搜索也保留轴。字段错误只重选字段，ordinal 顺序错误只修正 order；改变语义、方法或文件内容后重新展示摘要。未确认时 `analysis_args=null`，不得先运行统计。

直接诊断目录仍可用 `inspect --input FILE [--sheet-index N] [--page N | --search TEXT | --all-columns]`；第二次单选可加 `--exclude-index N`。名称与编号同时传入会校验一致性，不能借编号回退掩盖拼错的名称。

分析成功后按 [report-workflow.md](report-workflow.md) 交付 HTML 阅读入口与 Markdown 保存入口；使用返回的新路径字段，图和 CSV 作为报告附件。

## 可选网页选择器

仅用户明确请求可点击交换箭头的网页时，运行 `scripts/pair_picker.py --request <临时JSON路径>`（请求包含完整 state）。本地临时页面提供 X/Y 两字段框与交换按钮，不是默认流程；不能在宿主原生界面中注入该页面。

脚本首行返回 selection_url 后等待提交（默认 900 秒），进程仍在运行不代表失败，不重复启动。用户开始分析后才返回结果；取消/超时不分析，源文件变化拒绝旧提交。执行机的浏览器和本地端口须可用，ready 才能执行 analysis_args，needs_semantics 仍只补齐必要含义。
