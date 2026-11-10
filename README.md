# indiebiz-evidence

> **English** — An auditable evidence layer for your own periodic captures. Point it at a
> folder of dated CSV/JSON exports (competitor prices, job postings, listings, app metrics,
> changelogs — anything with an id, a date and some fields) and it gives you a queryable
> store, anomaly detection with explicit provenance, and a zero-dependency MCP server your
> agent can call. The point is not to collect more data; it is to stop believing wrong
> conclusions about the data you already collect.

把「每天抓的一堆 CSV」变成**可复核的证据库**：窄表事实库 + 异常检测 + 零依赖 MCP Server。
不依赖任何商业服务，不绑定特定数据源，**零运行时依赖**（纯标准库 + SQLite）。

## 它解决的不是"抓不到"，是"抓到了但结论是错的"

做采集的人最容易翻的三次车，都不是抓取失败：

| 翻车方式 | 后果 | 这里的做法 |
|---|---|---|
| 某个字段**悄悄不再输出**（页面改版） | 你以为"上游没这个数据了"，或根本没注意 | `audit_field_coverage` 逐字段给覆盖率，并在"以前有、最新没有"时判 ``absent_on_latest`，**先怀疑自己的抓取器** |
| 某条记录**整条消失**（下架/招满/撤稿） | 被当成"数据没抓到"或直接漏看 | `entity_disappeared`，并明确写"下架和漏抓从这里看一样，两处都要查" |
| 抓取**停了 30 天**，两个点被当成"隔了一天" | 每个指标都像一夜暴涨 | 学习该源自己的节奏；跨断档的变化明写跨度（如 `over 30 days`），不伪造精度 |
| 同一个东西**三种写法**拼不起来 | 三个实体，永远对不上 | `resolve_entities` / `find_duplicate_entities` 给**候选和证据**，绝不自动合并 |
| 缺失字段被当 0 | 有收入的项目被判成"零收入" | 缺席不落库、不参与比较、显示为缺席——**在查询层就成立，不靠你记得** |

## 五分钟上手（面向做采集的人）

[**docs/QUICKSTART-COLLECTOR.md**](docs/QUICKSTART-COLLECTOR.md) —— 用四天真实会踩坑的竞品价格数据，
带你从 `run_import.py` 到 `audit_source.py`，**每一段输出都是照抄实跑结果**（并用 CI 机制保证它不会漂移）。

```bash
python scripts/run_import.py --source competitors --input ./my-exports --db data/my.db
python scripts/audit_source.py --db data/my.db --source competitors   # 一句话健康报告
python scripts/mcp_server.py --db data/my.db                          # 给 agent 用的 stdio MCP
```

## 十一个 MCP 工具

| tool | 用途 |
|---|---|
| `list_sources` | 已导入的源、时间范围、实体/字段数（先调这个） |
| `audit_field_coverage` | **采集健康度**：逐字段覆盖率、`absent_on_latest` 判定、`schema_events`、断档节奏 |
| `search_records` | 任意字段筛选 + 排序 + 分页；**缺席字段永不满足比较** |
| `get_source_entity` | 单实体某日全字段快照 |
| `query_series` | 单字段全时序（缺口 = 缺席，不是 0） |
| `get_source_evidence_chain` | 单实体全字段跨日审计链 + 逐日 `raw_ref` |
| `diff_snapshots` | 两次抓取之间变了什么（新增/消失/逐字段），**与领域无关** |
| `list_entities` | 源内实体清单（首末次出现 / 出现的抓取日数 / 事实数） |
| `find_duplicate_entities` | 源内合并候选（`Acme Widget` vs `acme_widget`），带逐对证据 |
| `resolve_entities` | 跨源找同一个东西的各种写法——只给候选，不自动合并 |
| `list_source_anomalies` | 检测到的异常：数值摆动、数值摆动、累计回退、字段/实体消失、文本漂移、源改版、抓取断档 |

工具描述里写死了纪律：**解读任何变化前先查异常；缺失≠0；不跨身份边界做差；跨断档的变化不是一夜之间的；候选不是结论。**

## 检测规则（与领域无关）

| 类别 | 规则 |
|---|---|
| 数值 | `value_swing`（变动幅度）、`monotonic_regression`（声明为只增的量回退） |
| 身份 | `identity_change`（对比禁区）、`identity_rename_candidate`（改名候选） |
| 缺席 | `field_disappeared`（某列对某实体不来了）、`entity_disappeared`（整条记录消失） |
| 文本 | `text_changed`（仅对声明过的文本字段） |
| 源结构 | `field_appeared` / `field_gone` / `field_renamed_candidate`（源级伪实体 `__schema__`） |
| 节奏 | `gapped_transition`（断档超过该源正常节奏） |
| 时间戳 | `stale_timestamp`（源侧时间戳滞后） |

## 成熟度

**v0.5.x 是实验性版本**。已用：合成回归矩阵（13 场景）、103 项测试、文档真值检查。
**未用真实语料验证精度**——这条缺口写在 [COMPLIANCE.md](COMPLIANCE.md) §六，不藏着。
适用场景：本地、受信任输入、单机使用。不承诺处理任意规模或敌意输入。

## 安装

```bash
pip install .          # 零运行时依赖
python scripts/run_tests.py                       # 120 tests, 跳过=失败
python scripts/run_generic_precision_audit.py     # 精度门禁：13 个带标签场景
python scripts/check_docs_are_true.py             # 文档真值检查：照抄能不能复现
```

## 数据与隐私

**本仓库不含任何上游数据**：没有数据库、没有抓取内容、没有真实实体名。demo 全部是 2099 年的虚构实体。
`data/` 全目录 gitignored。详见 [COMPLIANCE.md](COMPLIANCE.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
