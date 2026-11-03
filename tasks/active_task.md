# 即时工作台

- WIP：0
- 状态：已完成。
- 关联：用户明确要求提交所有代码；Atomic Slice：S35 / 项目完整内容本地提交。
- 业务意图：将当前技能源码、运行资源、测试、README、协作规则和任务文档形成完整且可复查的本地 Git 提交。
- Non-Goals：不推送、打标签、发布或同步外部安装；不变更技能行为、Feature 完成状态或既有验收结论，不删除本地缓存和证据，不安装依赖，不修改模型记忆。
- 允许修改文件：.gitignore、tasks/active_task.md、skills/dasci-relationship/references/analysis-contract.md、skills/dasci-relationship/scripts/stats.py；前两者分别补充忽略规则和验收记录，后两者仅清理暂存检查发现的文件末尾多余空行，不改正文与代码语义；其他文件只审查和暂存现有内容。
- 暂存/提交范围：当前全部新增和修改的项目内容，即 .gitignore、README.md、AGENTS.md、skills/ 下两张 PNG、skills/dasci-relationship/ 的运行源码/模板/参考文档、tests/dasci-relationship/ 的源码/fixtures，以及 tasks/ 文档；以生成的显式文件清单暂存，不使用 git add -A，排除 __pycache__、*.pyc、虚拟环境、evidence 和敏感配置。核验期间外部新增的 skills/数据关系分析图标.png 按“提交所有代码”原样纳入，不修改其内容。
- 验收命令：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/dasci-relationship -p 'test_*.py' -v`；Python 标准库检查源码语法、JSON/模板/PNG 基本结构和本轮修改范围；`git diff --cached --check`、显式暂存清单及敏感内容扫描；本地 git commit 后核对提交内容与工作区状态。
- 验收选择依据：本次首次提交完整技能，覆盖当前唯一技能的全部自动化测试，不运行独立 Chromium 视觉工具或外部宿主交互验收；项目为 Python 技能，无 CMake target。既有 WorkBuddy 和浏览器待验收状态保持不变。
- 范围核验：每次 patch 后执行 git diff --name-only；以本轮开始时 75 文件哈希为基线，本轮仅修改上述四文件，并保存两处空行清理前内容以证明只改变末尾空行；另外记录外部新增图标的独立哈希并原样提交，逐项核对暂存文件不含缓存、证据或敏感配置。
- 时间盒：15分钟；冻结检查全部通过并完成本地提交、工作区核验后停止；遇到明确阻塞保留可复查证据，不擅自扩大源码修改范围。

## 完成证据

- 提交前依赖检查通过：numpy、pandas、Pillow、openpyxl、BeautifulSoup、markdown-it-py 和 Node.js 均可用；常见密钥标记扫描无命中。
- 当前唯一技能的完整自动化回归：216 项测试，38.040 秒，全部通过，无失败/错误/跳过；Node.js 控件验证实际执行。WorkBuddy 和 Chromium 真实界面验收仍按既有规格保持待完成。
- 两处 EOF 多余空行已清理，清理前后逐字比较确认仅删除空行，Python 语法检查通过，不重复执行无语义变化的全量回归；git diff --cached --check 通过。
- 29 个 Python 源文件语法、2 个 JSON 解析、原 512×512 技能图片解码与尺寸检查通过；55 个暂存文件逐项与工作区内容相同，缓存、证据与常见密钥标记检查通过。
- 核验期间外部新增 skills/数据关系分析图标.png：PNG/RGB、2048×2048、2,263,177 字节，解码通过，SHA256=e29b5c4d6b2fff12f271ba33059a62d206028156acd202ed0dc5c1f394095b55；原样加入最终 56 文件显式清单，不修改或覆盖现有技能图片。
- 本轮最终动作是已授权的本地 Git 提交，提交哈希与最终工作区状态以 Git 记录为准；WIP=0，不推送、发布或更改 Feature 状态。
