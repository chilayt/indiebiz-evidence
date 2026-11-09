# CHANGELOG

版本史摘要。

## v0.5.0 (2026-11-10)
- **首个公开发布版：通用引擎独立成仓**（从内部全量仓拆出）
  - 只含与数据源无关的通用层：CSV/JSON/JSONL 导入、窄表事实库、九类通用异常检测、十一个 MCP 工具
  - 垂直适配层（特定数据源的解析、报表、定向筛选）留在私有仓，不进公开物
  - `store.py` 只保留通用表（`generic_facts` / `sources` / `anomalies` / `ingest_files`）；垂直表不随公开包分发
  - `generic.py` 不再从垂直模块反向取辅助函数：`sync_lag_hours` / `likely_rename` 移入本仓 `_shared.py`
  - MCP Server 重写为通用版（11 工具），协议层与错误语义保持不变
  - docs/PATTERNS.md 保留九条纪律，事故证据链移至私有仓（公开层不再引用不存在的文件）
- 测试 0 → **93**（通用引擎 + MCP 协议端到端；干净 clone 上 0 skip）
- **公开首审（MiniMax）6 条 P1 已修**：
  - `search_records` 未知 op 被静默丢弃 → 返回全量且 `total_matched` 像"匹配数"；现在显式报错并列出允许的 op
  - filter 缺 `value` → `!=` 全中、`>=` 全不中；现在显式报错
  - `list_source_anomalies` 的 `count` 是截断条数而非总数；现在 `count`=总数，另给 `returned`/`has_more`/`truncated`
  - `diff_snapshots.anomalies_in_range` 只取两个端点日期，丢掉窗口中部（恰好是解释断档的那两条）；改为区间
  - `inf`/`1e999` 被解析成 Infinity → payload 不是合法 JSON，客户端整体解析失败；解析层拒绝非有限数，输出层再兜底
  - `search_records` 对未抓取日期返回 0 行 + 误导 hint；改为与 `diff_snapshots` 一致的显式错误
- 同批 P2：版本号三方统一为 0.5.0（此前包自报 0.4.2）；幽灵状态 `silent_drop` 从文档与工具描述中清除；悬空的 incidents 引用移除；`days_present` 改名 `capture_days_present` 并注明"抓取日数非自然日"；重复实体输出补 `truncated`、`overlapping_dates`→`same_day_overlap_days`、每对证据键统一；混合数值/文本字段改为显式拒绝而非按字符串排序；CLI 强制 UTF-8（GBK 控制台下文档真值检查不再崩溃）
- 三套门禁随仓发布：单元测试 / 通用精度审计（13 场景）/ 文档真值检查

## 更早版本

内部全量仓的 v0.1.0–v0.4.2（含垂直层与事故档案）不在本仓库内。
