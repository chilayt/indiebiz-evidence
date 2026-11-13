# CHANGELOG

版本史摘要。

## v0.8.0 (2026-11-13)
- **新增跨源实体对齐（entity_links）**——三方评审认定的"唯一值得新增的功能"，把跨源对齐从"每次手工重做"变成"做一次、存下来"：
  - `entity_links` 表（source+entity→canonical_id，存 decided_by/decided_at/evidence）。
  - `propose_entity_links`：跨源同名/近名候选 + 逐字段一致/冲突证据，**绝不自动连**。
  - `confirm_entity_link`：**人工确认**才建链（唯一建链方式），拒绝幻影实体/空 canonical_id。
  - `cross_check` 加 `canonical_id` 可选参数：用已确认对齐跨源比较，不再依赖名字恰好一致。
  - `list_entity_links`：按 canonical_id 分组查看。
  - 纪律不变：合并在人手里，工具只记住人的判断；候选不是结论。
- MCP 工具 12 → 15；新增 tests/test_entity_links.py 10 例（候选不自动连/确认存储/幻影拒绝/canonical 跨源异名/重确认替换），变异验证。
- 测试 158 / 0 skip

## v0.7.1 (2026-11-13)
- **按三方评审（Codex/Qoder/MiniMax）修分发断点与合规泄漏**：
  - **P0 合规泄漏**：v0.7.0 changelog 曾含上游平台名+真实匿名 slug+数值，已匿名化；COMPLIANCE 主动声明 commit message 残留；数据守卫新增上游名/真实实体文本扫描（负向测试验证可拦）。
  - **P0 Registry 启动死路**：mcp 缺库不再 exit 2，自动建空库并 serve，list_sources 空时返回导入指引；支持 INDIEBIZ_EVIDENCE_DB 环境变量。新增空库启动回归测试。
  - **P0 PyPI 安装命令**：README 改为首推 pip install indiebiz-evidence（PyPI 渲染的就是这份 README）；文档门禁新增断言防止漂回 pip install .。
  - 仓库元数据补齐（description/topics/homepage/discussions）；ROADMAP 更新到 v3（引擎冻结、转向分发与采用）。
  - 精度矩阵补 field_disappeared 正例（此前 TP=0，号称最重要的规则却无正例）；现 14 场景。
- 测试 148 / 0 skip

## v0.7.0 (2026-11-13)
- **新增 `identity_continuity_hint`（默认关）**：匿名实体的身份复用线索。源自真实数据验证——
  某公开数据平台的采集里，一个匿名 Stealth slug 先后指向了三家不同的公司（累计收入先骤降、后又跳升一个数量级），
  工具靠累计回退抓到，但因身份字段恒空无法自动标身份变更。（真实平台名/实体名/数值不在公开面披露。）
- 按 Codex 评审收紧实现：**不新增异常类型**，仅在 `monotonic_regression.detail` 追加提示；
  触发需"来源显式开启 + 声明了身份字段 + 截至回退日历史上所有身份字段无有效值"；
  文案明示"可能是退款/口径/解析/上游修正，尚未确认身份变更"（**累计回退≠必然换壳**，净累计可因退款合法下降）。
- **绝不**产生身份边界、抑制 value_swing、改 diff/跨源行为；身份曾有效则不提示；只看回退日前的历史。
- 新增 `tests/test_identity_continuity.py` 9 例（开/关、身份曾有效、身份后现、边界隔离、重跑去重），变异验证。
- 真实数据验证：13 个累计回退中 9 个获提示（另 4 个历史有 founder 值，正确不提示）。
- 测试 147 / 0 skip

## v0.6.1 (2026-11-12)
- **按 Codex 复核重写 cross_check**（复核结论：修 P1 前不能作为"多源复核"核心）。修复：
  - **孤证变佐证**：同源多写法（Acme/ACME）曾被算成"2 源一致"；现按**唯一来源**计数，同源多候选标记身份歧义
  - **raw_ref 丢失**：曾声称"每条带 raw_ref"但实际没返回；现每条观测独立保留 原文+抓取日+raw_ref，分组不折叠原文
  - **旧值冒充当前**：曾取实体最后有事实的日；现对照来源最新抓取，未在当前抓取报告的标"非当前"
  - **口径绕过**：`10%` 与 `10` 曾被折叠成"一致"；现新增 `numbers_match` 态（数值同但原文异=口径未确认，非佐证）
  - **数值相等用精确比较**：去掉 round(num,10)（会吞 4e-11、拆 2e-12）；近似比较需显式配置容差
  - 指定日期时列出未覆盖的候选源；携带身份边界异常；CLI 显示每条日期+出处
- **README 收回过度承诺**："让你采到的东西可信""一致=可信度高"改为"值相同不等于事实已核实，仍需确认实体/口径/时效/来源独立"
- cross_check 用例从 8 增到 12（Codex 每个反例一个回归）；总测试 138 / 0 skip

## v0.6.0 (2026-11-12)
- **新增跨源核对 `cross_check`（第 12 个 MCP 工具 + `indiebiz-evidence crosscheck` CLI）**——把定位从
  "盯时间序列"落到"**从多来源复核信息的真实性/有效性**"：
  - 给定一个实体，把**所有报告它的来源**的最新值按字段摆一起，判 **一致 / 打架 / 孤证**
  - 每条值带来源 + 抓取日 + 出处；某源未报告的字段记"未报告"，**不是 0**
  - 守住纪律：名字匹配是线索不是 join（只比精确归一化匹配）；**字段同名≠同口径/单位**，只摆值给人判断，不自动宣判；
    不同抓取日会显式提示"可能是时间差不是分歧"
  - 起因：`resolve_entities` 只匹配名字不比对值，"多源复核"此前是空的；本功能把它做实
- README 重新定位到"先核实再下结论"，新增跨源核对实例与工具表条目
- 新增 `tests/test_cross_check.py`（8 例：冲突/一致/孤证/缺席≠0/精确匹配/字段过滤/无匹配/异日期）
- 测试 134 / 0 skip

## v0.5.6 (2026-11-11)
- **按 Codex 复核修复阶段1**（复核结论：部分通过，反对默认清空）
  - **空重导默认拒绝破坏性替换**：零事实导出替换"已有事实的日期"默认**拒绝**（保留旧事实+旧批次+响亮提示），
    显式 `--allow-empty-replace` 才清空。判断基于**解析后可用事实数**（覆盖"有记录但字段全空"），不只查 `records==[]`。
    C-SPEC 本就允许"清空或明确拒绝"，故选拒绝为默认。
  - **修"报失败但已提交删除"**：CLI 不再因 `facts==0` 提前 exit 3（那会跳过检测、留下旧异常）；
    只在 `files==0` 或 `errors>0` 时失败，空捕获/被拒替换都继续跑检测保持一致。
  - **空批次可见**：`list_sources` 新增 `latest_capture_date`/`latest_fact_date`/`latest_capture_empty`；
    终端审计显式提示"最新抓取为空批次+覆盖率参照日"，不再让"无异常"冒充"采集健康"。
  - **修空转测试 C03**：diff 断言原来在实体层找 `field`（实际在嵌套 `changes`），且默认比较不跨边界→从没执行。
    现显式跨边界比较、进入嵌套字段、断言确实查到价格变化；变异验证可抓缺陷。
  - **selftest 编码**：`mcp --selftest` 补 UTF-8 stdio（CP936+emoji 曾崩，CI 全局编码掩盖了它）。
  - **依赖守卫按 3.11+ 简化**：删 stdlib/tomllib 回退与 3.9 模拟测试（契约已 >=3.11）。
  - **安装验收增强**：CI 改跑真正的 `indiebiz-evidence` 控制台命令 + 仓库外**真实 stdio 握手**（initialize+tools/call）。
- 测试 126 / 0 skip

## v0.5.5 (2026-11-11)
- **Python 下限提到 3.11**（契约变更，`requires-python = ">=3.11"`）
  - 起因：跨平台 CI 首跑，ubuntu-latest（26.04）已不再为 3.9 构建解释器，`test (ubuntu, 3.9)` 失败；
    windows/macos 的 3.9 仍可用——这不是代码 bug，是 EOL 版本不再有 CI 支持
  - 3.9/3.10 均已 EOL（2026-11）。继续承诺它们只会不断制造这种摩擦；Codex 此前已建议提到 3.11
  - CI 矩阵改为 **3.11 / 3.13**（下限 + 近期版本）；依赖守卫的 stdlib 回退保留为防御性兜底
  - 可逆：若将来要支持更老版本，须同时恢复对应验证，不能只改声明
- **修复 CI 工作流本身**：上一版一个 `run:` 行以引号开头，YAML 解析失败，导致矩阵加进来后**所有 run 都 0s 失败、从未真正执行**。
  改为块标量 + heredoc，并用真实 YAML 解析器校验。教训：「本地门禁过」和「CI 绿」是两个不同的断言
- 测试 125 / 0 skip

## v0.5.4 (2026-11-11)
- **C05 空快照语义落地**（阶段 1 的正确性项，此前以 expectedFailure 记录为已知失败）
  - 带日期的空导出 = "该日采到了、但零事实"：记入时间轴（批次 facts=0），不再从时间轴上消失
  - 同日期重导为空按 REPLACE 语义清空该日旧事实，与非空重导一致
  - **清空已有数据必须响亮警告**（空文件常是抓取器坏了）——破坏性操作不静默
  - 两个 expectedFailure 转为真实断言；变异验证：退回"空文件静默跳过"→ 两测试变红
  - 语义决定记录在 docs/acceptance/C-SPEC.md C05 与交接记录；预期未改，是实现达到冻结预期
- 测试 125 / 0 skip（不再有 expectedFailure）

## v0.5.3 (2026-11-10)
- **C03–C08 独立验收落地**（`tests/test_acceptance_c_spec2.py`，同一份冻结的 C-SPEC）
  - C03 身份边界：边界可见、不跨边界算涨跌、`delta_pct` 为 null
  - C04 断档跨度：`span_days=30`（顶层与每条变更都必须），`cadence_note` 说明真实跨度
  - C05 空快照：**两个已知失败**按 `expectedFailure` 记录，不悄悄修掉
    - 新增空捕获不进时间轴
    - 同日期重导为空会留下旧事实
  - C06 重导一致性：旧字段不残留、重复检测结果稳定
  - C07 编码与来源：GBK 两个中文 ID 不合并、`raw_ref` 指向真实文件、中文空格路径可用
  - C08 源隔离与错误：`shop`/`workshop` 时间轴独立；未抓取日期明确报错
- **变异测试验证有效性**：禁用边界检查、伪造跨度、不清理旧事实、退回 replace 解码、
  允许未抓取日期——五个变异**全部被杀死**
- 测试 125 / 0 skip（含 2 个 expectedFailure）
- **阶段 1：装完即用（跨平台）**
  - 演示数据随包分发（`demo_data/`），`pip install` 后在**任意目录**可跑，不再依赖仓库目录
  - 新增安装命令 `indiebiz-evidence`（demo / import / audit / mcp 四个子命令）；审计逻辑入包（`reporting.py`）
  - 所有 CLI 路径相对**当前工作目录**解析（旧脚本相对仓库根，换个目录就坏）；`--input` 不存在时明确报错退出
  - CI 改为矩阵：ubuntu/windows/macos × Python 3.9/3.12，另设**安装验收** job（建 wheel→全新 venv→仓库外跑 demo/audit/mcp）
  - 文档检查器 `shlex.split(posix=False)`：既保住带空格的路径，又不吃掉 Windows 反斜杠
  - README 改为 **demo 前置**（不用先有自己的数据），补 MCP 宿主配置片段与路径规则；QUICKSTART 补 demo 入口
  - 新增 `tests/test_cli.py`（安装入口 + CWD 相对路径）

## v0.5.2 (2026-11-10)
- **独立合成验收 C01/C02 落地**（按冻结的 `docs/acceptance/C-SPEC.md`）
  - `tests/test_acceptance_c.py`：C01 缺失与零分开（删掉整列 vs 显式 0，含 `== 0` 与 `> 0` 六个日期×算子组合）、
    C02 告警精确归属（完整告警清单只允许一条，落在指定实体+字段+日期，detail 含两个数值）
  - **变异测试验证有效性**：把"缺失当 0"注入 `search_records`、把告警挂到错误实体，两个变异都被测试杀死
  - 修 `_read_text` 的文件句柄泄漏（上一版严格解码改造引入，ResourceWarning）
- 测试 112 / 0 skip

## v0.5.1 (2026-11-10)
- **转公开前的维护基础设施**（按 Codex 维护方案的最小集合 A–G）
  - **防误提交真实数据**：新增 `scripts/check_no_real_data.py`，拦 `data/` 类目录、数据库/导出/凭据扩展名
    与已知凭据标记；同一份检查同时用于 `git commit`（`.githooks/pre-commit`）与 CI。检查只打印路径与原因，不打印内容。
  - **零运行时依赖从承诺变成契约**：`scripts/check_no_runtime_deps.py` 校验 pyproject 声明、包内 import
    与安装后元数据三处，CI 必跑。
  - **安全报告渠道闭环**：`SECURITY.md` 改用 GitHub private vulnerability reporting，写明响应目标（7 天）与
    "只支持最新版"。
  - **贡献规范**：新增 `CONTRIBUTING.md`，明确不接受采集器/运行时依赖/真实数据/无法评分的检测规则，
    以及版本与支持政策。
  - **精度声明收口**：`COMPLIANCE.md` §六把"合成回归矩阵""文档真值检查""真实语料抽样"三件事分开，
    承认第三项未完成且不阻塞实验性首发；README 增加"成熟度"段。
- **Codex 复审 0.5.1 发现守卫自身三处"看起来在检查、其实没检查"**，已修并加回归：
  - git 失败时输出"检查了 0 个文件"并返回成功 → 现在 git 失败、返回错误码、文件列表为空都**必须失败退出**
  - 暂存模式读的是工作区内容，`git add` 之后的修改会决定检查看到什么 → 改为读**暂存区 blob**（`git show :path`）
  - Python 3.9 分支的 stdlib 清单不全，`__future__`/`unicodedata` 被误判为第三方依赖（CI 3.9 会红）→ 补全清单，并拒绝字符串形式的非空依赖声明
- 新增 `tests/test_guards.py` 把上述失败路径全部钉住：测试 110 / 0 skip
- 新增 `docs/acceptance/C-SPEC.md`：**先冻结**八个独立验收用例的预期，再运行，避免用实现反推预期；
  C05(b)（同日期完整快照重导为空会留下旧事实）记为已知失败，正式执行而不悄悄修掉

## v0.5.0 (2026-11-10)
- **首个公开发布版：通用引擎独立成仓**（从内部全量仓拆出）
  - 只含与数据源无关的通用层：CSV/JSON/JSONL 导入、窄表事实库、通用异常检测、十一个 MCP 工具
  - 垂直适配层（特定数据源的解析、报表、定向筛选）留在私有仓，不进公开物
  - `store.py` 只保留通用表（`generic_facts` / `sources` / `anomalies` / `ingest_files`）；垂直表不随公开包分发
  - `generic.py` 不再从垂直模块反向取辅助函数：`sync_lag_hours` / `likely_rename` 移入本仓 `_shared.py`
  - MCP Server 重写为通用版（11 工具），协议层与错误语义保持不变
  - docs/PATTERNS.md 保留九条纪律，事故证据链移至私有仓（公开层不再引用不存在的文件）
- 测试 0 → **103**（通用引擎 + MCP 协议端到端；干净 clone 上 0 skip）
- **发布前审（Codex）P0：输入解码会静默损坏数据**——GBK 编码的 CSV 里两个不同的中文 ID 都被
  `errors="replace"` 解码成 U+FFFD，合并成一个实体、只剩最后一行、**零警告**。
  现在改为**严格解码**：UTF-8 优先、GBK 回退、都失败则报错并计入 `errors`（不再是猜测或静默替换）。
  同时修 `_to_num` 的数字类型分支：`inf`/`nan` 可通过早返回绕过有限性检查（JSON 里的 `1e999` 即中招）。
- **公开复审第二轮（Codex + MiniMax）修复**：
  - `value: null` 的过滤器仍复现原缺陷（`!=` 全中、`>=` 全不中）：键存在但值为 null 现在与缺键同等对待
  - `monotonic_regression` 分支漏了区间边界检查（`ALPHA/1000 → ZULU/缺席 → ZULU/10` 仍报回退）：已与其它规则统一
  - **批次台账改显式**：此前用文件路径子串匹配 source，导致不同源的时间轴互相污染（shop / workshop）、
    且失败批次仍被吞。新增 `capture_batches` 表按 (source, date) 记录每次导入（含 0 事实批次）
  - **批次状态与字段状态分离**：`latest_batch.empty` 单列，不再覆盖字段自己的 `absent_on_latest`，
    消除和 `schema_events` 的状态矛盾
  - 文档数字门禁扩大覆盖面：README 的测试数/场景数、CHANGELOG 的工具数现在都校验，解析不到即失败
  - COMPLIANCE 重写为纯发布口径（上一轮那次写入因脚本报错未落盘，本轮确认写入）；SECURITY 去掉不可用的
    `maintainer@localhost`，改为"开只说需要私密渠道的 issue"。
- **公开首审（Codex）两条 P1 已修**：
  - **身份边界藏在断档里**：day1 ALPHA/10 → day2 ZULU/价格缺席 → day3 ZULU/900，检测器仍报 +8900%。
    根因是只检查比较区间终点当日是否为边界，没检查区间内部。改为检查 `(d0, d1]` 全区间。
  - **零事实批次被吞掉**：某次抓取导入 0 条可用事实时，覆盖率把上一次抓取当作最新并报 100%，
    失败被旧数据遮住。现在时间轴含 `ingest_files` 中成功的批次，覆盖率显式报
    `latest_capture_empty` / `no_facts_in_latest_capture` 并说明覆盖率以哪一天为锚。
  - MCP 错误语义：返回体里带 `error` 的工具调用现在同时置 `isError: true`（此前是 false，宿主会把
    "缺参数"当成数据读）。
- 同批文档修正：COMPLIANCE 重写为发布口径（移除内部决策、采集规模与不存在功能的引用）；
  `check_numbers` 不再空转（中文字数解析、取最新版本段、解析不到即失败）；删除悬空的事故引用与
  "v0.4 会有"的未来承诺；"口径矛盾"这一不存在的检测能力从 README 移除；SECURITY 填实报告渠道。
- **公开首审（MiniMax）6 条 P1 已修**：
  - `search_records` 未知 op 被静默丢弃 → 返回全量且 `total_matched` 像"匹配数"；现在显式报错并列出允许的 op
  - filter 缺 `value` → `!=` 全中、`>=` 全不中；现在显式报错
  - `list_source_anomalies` 的 `count` 是截断条数而非总数；现在 `count`=总数，另给 `returned`/`has_more`/`truncated`
  - `diff_snapshots.anomalies_in_range` 只取两个端点日期，丢掉窗口中部（恰好是解释断档的那两条）；改为区间
  - `inf`/`1e999` 被解析成 Infinity → payload 不是合法 JSON，客户端整体解析失败；解析层拒绝非有限数，输出层再兜底
  - `search_records` 对未抓取日期返回 0 行 + 误导 hint；改为与 `diff_snapshots` 一致的显式错误
- 同批 P2：版本号三方统一为 0.5.0（此前包自报 0.4.2）；代码并未产出的一个状态名从文档与工具描述中清除；悬空的 incidents 引用移除；`days_present` 改名 `capture_days_present` 并注明"抓取日数非自然日"；重复实体输出补 `truncated`、`overlapping_dates`→`same_day_overlap_days`、每对证据键统一；混合数值/文本字段改为显式拒绝而非按字符串排序；CLI 强制 UTF-8（GBK 控制台下文档真值检查不再崩溃）
- 三套门禁随仓发布：单元测试 / 通用精度审计（13 场景）/ 文档真值检查

## 更早版本

内部全量仓的 v0.1.0–v0.4.2（含垂直层与事故档案）不在本仓库内。
