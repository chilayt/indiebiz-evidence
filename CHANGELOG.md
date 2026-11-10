# CHANGELOG

版本史摘要。

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
- 测试 120 / 0 skip（含 2 个 expectedFailure）

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
