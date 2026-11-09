# ADAPTERS：接入你自己的数据源

> 通用 adapter 的约定与配方。**任何“周期性快照”都能进同一套证据库、同一套异常检测、同一个 MCP。**

## 一、目录约定

```
exports/my-prices/            ← --input 指向这里
  source.json                 ← 可选：字段角色声明（见 §三）
  2026-11-06.csv              ← 日期必须在文件名开头（YYYY-MM-DD 或 YYYYMMDD 前缀）
  2026-11-07.csv
  2026-11-07.json             ← CSV / JSON / JSONL 均可，同日可混用
  2026-11-07.jsonl            ← JSONL=每行一个 JSON 对象（gh api 追加式导出友好）
```

> 硬规则：**日期在文件名开头**。`stars-2026-11-07.jsonl` 这种日期在结尾的命名不识别（宁缺不猜）；文件内行级 `observed_date` 列可替代文件名日期。

- 文件名没有日期时，行内必须有 `observed_date` 或 `date` 列（可在 source.json 用 `date_column` 指定别的列名）。
- 导入命令：

```bash
python scripts/run_import.py --source my-prices --input exports/my-prices
# 之后 MCP 工具即可查：list_sources / get_source_entity / query_series
#                     / audit_field_coverage / search_records / get_source_evidence_chain
#                     / diff_snapshots
#
# 建议第一次导入后先跑 audit_field_coverage：
#   它会逐字段报覆盖率，并在"以前抓得到、最新一天没有"时给出 silent_drop，
#   这通常是你的抓取器/解析器少输出了字段，而不是上游没了这个数据。
# 异常命名空间：<source>:<entity>（如 my-prices:widget-a）
```

- **幂等**：重复导入同一文件覆盖同键事实，检测自动重跑。
- **实体列**自动识别顺序：`--entity-column` 参数 > source.json 的 `entity_column` > `entity/name/slug/id/product/repo/app/keyword` 中第一个存在者 > 第一列。

## 二、数据纪律（导入器强制）

| 规则 | 行为 |
|---|---|
| **缺失 ≠ 0** | 键不存在、值为 null、空字符串 → **不落库**（是“缺席的事实”，查询时表现为该日无此行） |
| **占位符 = 缺席**（P0-B） | `"N/A" / "NA" / "-" / "--" / "null" / "none" / "nan"`（大小写不敏感）同样不落库并计入 skipped_values；集合可用 `null_markers` 覆盖。否则 field_disappeared 永不触发 |
| **单位语义保留**（P0-A） | `"12%"` → num=12 **且 text="12%"**；`"$99"` → num=99 且 text="$99"。text 列**永远保存原文**，不因 num 解析成功而置空——百分号/货币口径可判。逗号只认严格三位分组：`"12,5"` 属地区歧义，**拒绝猜测**、仅存 text |
| **单位一致性由导出方负责** | 同一 `(source, entity, field)` 内勿混用 `12%` 与 `0.12`：num 按字面入同一序列，检测层不做单位归一化（宁缺不猜） |
| **显式列名错误必须炸** | `entity_column`/`date_column` 指向不存在的列 → ERROR 落日志 + run_import 非零退出，绝不静默 0 事实 |
| **日期强校验**（P0-D） | observed_date 只接受真实历法 `YYYY-MM-DD`；`11/07/2026` 这类歧义格式**拒绝入库**（skipped_records+invalid_dates 计数并 WARN），宁缺不猜 |
| **实体/日期列透明解析**（P0-C） | 每个文件打印 entity_column 与 date_source（filename 或 column:<名>）；自动识别命中多个候选（如同时有 name 和 sku）时 WARN 并要求人工确认；结果持久化进 sources.config._resolved 可断言；`--entity-column` 强制覆盖 |
| **`date` 列防误认** | 仅当无 observed_date 列且 source.json 未显式指定时才把 `date` 当抓取日，并打“歧义列名”WARN（date 常是业务字段） |
| **同日双文件告警**（P1-B） | 同一 (source, date) 由两个文件供数 → WARN + ingest_files 记 warn 行；导入采用**按 (source, date) 先清后写**的替换语义——修订版文件重导不会残留旧事实（幽灵值） |
| **身份边界贯穿检测** | `identity_change`（high）发生的捕获日构成该实体的**对比边界**：跨边界的 value_swing / monotonic_regression 一律抑制（换主体的"变动"不是信号），field_disappeared 附边界注记；`query_series` 返回 `identity_boundaries` 与警告 |
| 可回溯 | 每条事实带 raw_ref → 来源文件路径 |

## 三、source.json 字段角色（声明后才有对应检测）

```json
{
  "entity_column": "product",
  "monotonic_fields": ["cumulative_units"],
  "identity_fields": ["owner"],
  "timestamp_fields": ["updated_at"],
  "swing_fields": null,
  "swing_threshold": 0.30,
  "min_presence_days": 3,
  "stale_hours": 48,
  "null_markers": ["", "n/a", "na", "-", "--", "null", "none", "nan"],
  "date_column": null
}
```

| 角色 | 触发的异常 | 严重度 |
|---|---|---|
| `monotonic_fields`（只增不减的累计量） | `monotonic_regression:<field>` | warn |
| `identity_fields`（归属/主体标识） | 突变=`identity_change:<field>`（跨日对比禁区）；字符串包含关系=`identity_rename_candidate:<field>` | high / info |
| `timestamp_fields`（源侧更新时间） | `stale_timestamp:<field>`（滞后 > stale_hours） | warn |
| 其余数值字段（或显式 `swing_fields`） | `value_swing:<field>`（≥ swing_threshold） | info |
| **所有字段**（无需声明） | `field_disappeared:<field>`：连续 ≥ min_presence_days 次出现后突然缺席 | warn |

> `field_disappeared` 是本项目最重要的一条通用规则——它就是“GSC 字段消失 13 天”事故的制度化防线：**字段缺席时先怀疑源和解析器，再下“被移除”的结论**（证据链：docs/incidents/08）。
>
> `min_presence_days` 按**该实体的连续捕获次数**计（非自然日）。默认 3 次适合日更源；周更源建议 2；**demo 配置里的 1 仅为让两天夹具能触发，不是推荐值**。

## 四、配方

### GitHub 仓库指标（用你自己的 gh 导出，本项目不抓取）

```bash
# 每天一行 cron（你自己的机器上）：
gh api repos/OWNER/REPO --jq '{repo: .full_name, stars: .stargazers_count, forks: .forks_count, open_issues: .open_issues_count, pushed_at: .pushed_at}' >> exports/gh-stars/$(date +%F)-stars.jsonl
# 注意：日期前缀必须在文件名开头；.jsonl 每行一个对象，追加式导出直接可用
python scripts/run_import.py --source gh-stars --input exports/gh-stars
# source.json: {"entity_column":"repo","monotonic_fields":[],"identity_fields":[],"timestamp_fields":["pushed_at"]}
```

### 竞品价格监控

CSV 三列即可：`product,price,observed_date`；source.json 声明 `identity_fields: ["vendor"]`（换供应商=对比禁区）、swing_threshold 0.1（价格波动 10% 就报）。

### App 榜单 / 关键词量 / 岗位数

同构：实体列 + 若干数值列 + 日期。**导出格式不限**（Excel 另存 CSV、API 返回存 JSON、甚至手抄表格），只要满足 §一 约定。

## 五、边界（诚实声明）

- 不做抓取、不做调度——你负责“定期导出”，它负责“导出之后的一切”；
- 单文件一次性数据没有时序价值（至少两个捕获日才能对比）；
- 非结构化声明核验（长文/截图/聊天记录）不适用本 adapter；
- **行级业务日期（business_date）与捕获批次表在 v0.4**：当前“一个文件的日期=该文件所有行的捕获日”，行内 `date` 列会被当捕获日（带歧义 WARN）。“一份导出含 30 天历史行”的形状请暂拆成按日文件，或等 v0.4。


## 采集的不是数字？——文本/条目型数据同样适用

引擎最早是给"营收数字"写的，但**它不要求你的数据是钱**。抓职位、论文、房源、商品条目、
更新日志、公告，一样能用；需要多声明两件事。

```json
{
  "entity_column": "job_id",
  "identity_fields": ["company"],
  "track_text_fields": ["title", "status", "posted_text"],
  "min_presence_days": 2
}
```

| 键 | 作用 | 不配会怎样 |
|---|---|---|
| `track_text_fields` | 声明哪些**文本字段的内容变化**值得记一条异常（改标题、open→closed、描述被改写） | 文本变化完全不检测——数值规则对文本是瞎的 |
| `min_presence_days` | 实体**整体消失**（下架/招满/撤稿）要连续出现几天才报 | 默认 **3**；轮换型榜单（每日 Top-N）建议再调高，否则天天报警 |

配套的两个能力：

- **`entity_disappeared`**：整条记录不见了（`field_disappeared` 管的是"某一列不来了"）；
- **`diff_snapshots`**：任意两次抓取之间——新增了谁、消失了谁、哪个字段从什么变成什么。

实测（四天职位抓取，两个真实坑）：

```
[detect:jobs] entity_disappeared           1
[detect:jobs] text_changed                 2

2026-11-03  jobs:j002  text_changed:title   info
    title changed 'Product Designer' -> 'Senior Product Designer'
2026-11-03  jobs:j003  text_changed:status  info
    status changed 'open' -> 'closed'
2026-11-04  jobs:j003  entity_disappeared   warn
    entity absent on 2026-11-04 after 3 consecutive capture(s) -- delisted/removed,
    or your crawler missed it; check the source before concluding removal
```

> `entity_disappeared` 的文案刻意不写"已下架"——**下架和漏抓从这里看长得一模一样**，
> 这正是纪律 8 要防的那种自信。


## 源改版了？——列集合本身的变化也会被报出来

抓取的人最先撞上的不是"某个值变了"，而是**页面上那一列没了 / 多了一列 / 改名了**。这类事
不属于任何单个实体，所以单独作为**源级事件**报出（异常 slug 用 `<source>:__schema__`）：

| 检测 | 含义 | 严重度 |
|---|---|---|
| `field_appeared:<f>` | 某列第一次出现，且当日**覆盖全部实体** → 源改版或你的提取器开始输出它 | info |
| `field_gone:<f>` | 某列此前覆盖全部实体，当日**对全部实体都消失** → 源的形状变了 | warn |
| `field_renamed_candidate:<旧>-><新>` | 同日一列消失、一列出现，**同一批实体**、值相似 → 大概率是改名 | info |

两条设计纪律：

1. **只在"转变日"报一次**，不在之后每天都报（否则一条消失的列会天天刷屏）；
2. **只报"全实体"级别的变化**。某一列只对部分实体缺失，那是逐实体漂移，归 `field_disappeared` 管，
   不重复报。这样两条规则不会互相打架。

实测（第 3 天页面改版：`price` 改名 `cost`，新增 `currency`）：

```
2026-11-03  shop:__schema__  field_appeared:cost      info
2026-11-03  shop:__schema__  field_appeared:currency  info
2026-11-03  shop:__schema__  field_gone:price         warn
2026-11-03  shop:__schema__  field_renamed_candidate:price->cost  info
    'price' vanished and 'cost' appeared on the same date; same entities (3),
    similar values (3/3) -- likely one column renamed (confirm before migrating your config)
```

`audit_field_coverage` 的输出里也有对应的 `schema_events` 汇总
（`fields_added_after_first_capture` / `fields_missing_on_latest`），
不用翻异常表也能一眼看到"我这个源这阵子形状变过"。

> 改名只给**候选**，不给结论：值通常也会跟着动，所以文案里把"同实体数 / 相似值数"直接摆出来，
> 让你自己判断——迁移配置之前必须人工确认。

## 抓取断档了？——不会再把 30 天读成"隔了一天"

引擎默认"抓取日连续"。但真实采集会停：出差、封禁、脚本挂了、改成每周抓一次。
断档本身不是错，**把断档当成相邻两天才是错**。

现在会先算这个源的**正常节奏**（相邻抓取日间隔的中位数），然后把超出
`max(2 × 中位数, max_gap_days)` 的间隔标出来：

| 检测 / 字段 | 含义 |
|---|---|
| `gapped_transition`（info，源级） | 某日之前有 N 天断档，跨这条边界的任何变化都跨了 N 天 |
| `value_swing` 文案追加 | `... (+50%) over 30 days (capture gap; not a one-day move)` |
| `field_disappeared` / `entity_disappeared` 文案追加 | `-- after a 30-day capture gap; absence may be normal churn in that window` |
| `audit_field_coverage.cadence` | `median_gap_days` / `max_gap_days` / `gaps_over_threshold` |

实测（每天抓，然后停了 30 天，价格真的涨了 50%）。下面是从 `audit_source.py` 输出里原样摘的异常段：

```
抓取断档
  2026-11-02 之前断了 30 天

异常（3）
  2026-11-02  cat:__schema__                 gapped_transition      info
      capture gap of 30 day(s) before 2026-11-02; this source's normal cadence is 1.0 day(s) from 2 earlier capture(s) (threshold 2.0) -- changes across this boundary span 30 days, not one
  2026-11-02  cat:a                          value_swing:price      info
      price moved 100.0 -> 150.0 (+50%, threshold 30%) over 30 days (capture gap; not a one-day move)
  2026-11-02  cat:a                          value_swing:views      info
      views moved 1020.0 -> 1500.0 (+47%, threshold 30%) over 30 days (capture gap; not a one-day move)
```

注意两件事：参照值是 **1.0**（不是 1），并且文案写明了**参照来自 2 次先前抓取**、阈值 2.0——
读者能自己复核这个判断是怎么来的。
配置 `max_gap_days` 可以放宽容忍度（比如你就打算每周抓一次，设 10 天）：

```json
{ "entity_column": "sku", "max_gap_days": 60 }
```

> **为什么不直接压制断档期间的检测**：变化是真的发生了，压掉就是丢信息。
> 做法是**保留检测、把跨度写在脸上**——让读的人知道这是 30 天的变化而不是一夜之间。
> 这跟"缺失≠0"是同一种诚实：不伪造精度。


## 同一个东西，三个名字？——跨源实体对齐

采集的第二堵墙不是"抓不到"，而是"**抓到了但拼不起来**"。同一个产品在三份导出里叫
`Acme Widget` / `acme-widget` / `ACME_WIDGET`，就变成三个实体，永远对不上。

三个工具，**都只给候选、不做合并**：

| 工具 | 回答什么 |
|---|---|
| `list_entities` | 这个源里我到底在跟踪哪些实体（首末次出现、出现天数、事实条数，轻量分页） |
| `find_duplicate_entities` | **源内**哪些实体折叠后是同一个键（`Acme Widget` 与 `acme_widget`） |
| `resolve_entities` | 拿一个名字，去**所有源**里找它的各种写法 |

归一化只做最保守的三件事：**大小写、空白、分隔符**（`- _ . · / \`）。

```
'Acme Widget'  -> acmewidget
'acme-widget'  -> acmewidget
'ACME_WIDGET'  -> acmewidget
```

实测（shop 源两个写法 + ads 源一个写法）：

```
find_duplicate_entities("shop")
  key=acmewidget  entities=['Acme Widget','acme_widget']
  overlapping_dates=2  overlap_kind=same_day

resolve_entities("acme widget")
  matches: 3
  ads  | ACME-WIDGET  | exact_normalized
  shop | Acme Widget  | exact_normalized
  shop | acme_widget  | exact_normalized
```

### 为什么不做模糊匹配 / 自动合并

1. **编辑距离会造出"看起来很确信"的错误连接**——比不连接更糟。宁可漏连，不可错连。
2. **归一化本身就会碰撞**：`a/b` 与 `a-b` 都折叠成 `ab`，但它们可能是两个东西。
3. 所以输出里带 **`overlapping_dates`**（两两取最大值）与 **`overlap_kind`**：

   - `same_day`：两个写法**至少有一天同时出现** → 可以**排除改名**（改名不可能同日并存），
     但仍可能是"一个东西的两行"或"真的碰撞"——**要对比字段值才能判断**；
   - `disjoint`：从未同日出现 → 与**改名**一致，也与"一个走了另一个来了"一致。

   `overlapping_dates > 0` **不是**身份结论。上一版这里曾输出 `likely_same_entity=True`，
   那是一个我们无法支撑的身份判断，已删除。

合并与否由人决定。工具只负责把证据摆整齐。
