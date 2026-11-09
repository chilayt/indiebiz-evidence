# 五分钟上手：你有一堆抓来的 CSV，这套东西能立刻告诉你什么

> 场景：你在盯三个竞品的价格。每天抓一次，存成 CSV。
> 这份教程用的**数据是真实会踩的坑**，且下面每一段输出都是**用本页命令实跑出来的**——
> 你可以完全照抄复现（四天完整数据见 §0）。

## 0. 准备数据：四天，四个文件

文件名带日期（`YYYY-MM-DD` 前缀），内容如下。第 3 天开始，你的抓取器悄悄出了两个问题（你还没发现）：

- `stock_status` 那一列**还在表头里，但值全空了**（页面改版，选择器失效）；
  列被删掉和列还在但为空，工具分不出来，下面会看到它原话这么说；
- beta-gadget 的价格从 99 跳到 990（**原因未知**：可能是货币/小数点解析错误，也可能是真涨价——工具只负责告诉你它跳了）。

`2026-11-01-competitors.csv`

```csv
product,price,stock_status,rating,units_sold
acme-widget,49.00,in_stock,4.5,120
beta-gadget,99.00,in_stock,4.1,80
gamma-tool,19.00,out_of_stock,3.9,45
```

`2026-11-02-competitors.csv`

```csv
product,price,stock_status,rating,units_sold
acme-widget,52.00,in_stock,4.5,131
beta-gadget,99.00,in_stock,4.2,88
gamma-tool,19.00,in_stock,3.9,52
```

`2026-11-03-competitors.csv`

```csv
product,price,stock_status,rating,units_sold
acme-widget,55.00,,4.6,145
beta-gadget,990.00,,4.2,95
gamma-tool,19.00,,3.9,61
```

`2026-11-04-competitors.csv`

```csv
product,price,stock_status,rating,units_sold
acme-widget,58.00,,4.6,160
beta-gadget,990.00,,4.2,101
gamma-tool,19.00,,3.9,70
```

## 1. 导入

```bash
python scripts/run_import.py --source competitors --input ./my-exports --db data/my.db
```

实跑输出（末尾几行）：

```
[detect:competitors] value_swing                  1
[import] anomalies for competitors: {'value_swing': 1, 'field_gone': 1}
[import] query via MCP: list_sources / get_source_entity / query_series (anomaly slug namespace 'competitors:<entity>')
```

## 2. 先问"我的采集还健康吗"（这一步最值钱）

```bash
python scripts/audit_source.py --db data/my.db --source competitors
```

实跑输出：

```
== 数据源 competitors ==
抓取日 4 天 | 实体 3 个 | 字段 4 个 | 参照间隔 1.0 天

字段覆盖
  字段                     覆盖       出现       最新实体  状态
  price              100.0%      4/4        3/3  ok
  rating             100.0%      4/4        3/3  ok
  stock_status        50.0%      2/4        0/3  ABSENT-NOW
       -> ABSENT-NOW: no still-present entity reports this field on the latest date. The column may have been removed, renamed or emptied -- the fact table stores no null cells, so it cannot tell these apart. Check the raw file before concluding the source changed.
  units_sold         100.0%      4/4        3/3  ok

源结构变化（列可能被删除/改名/变空，需查原始文件确认）
  - stock_status     最后出现 2026-11-02

节奏未知（此前无抓取可参照，既不判为断档也不判为正常）
  2026-11-02

异常（2）
  2026-11-03  competitors:__schema__         field_gone:stock_status warn
      no entity reports a value for 'stock_status' on 2026-11-03 (every entity did on 2026-11-02). The column may have been removed from the export, or it may still be present but empty -- the fact table stores no null cells, so it cannot tell these apart. Check the raw file before concluding the schema changed.
  2026-11-03  competitors:beta-gadget        value_swing:price      info
      price moved 99.0 -> 990.0 (+900%, threshold 30%)
```

**这就是第一件你会庆幸有的事**：`stock_status` 覆盖率掉到 50%，状态 `ABSENT-NOW`，
并且直接指出"每一个仍然存在的实体都丢了这一列"。

没有它，你有两种反应，**两种都是错的**：

1. 以为"竞品不再公开库存了" → 得出一个关于市场的错误结论；
2. 根本没注意到 → 后面所有"缺货"分析都建在残缺数据上。

真相是**你自己的抓取器坏了**。这是 `docs/PATTERNS.md` 的纪律 8（缺席先怀疑自己），
它的原始事故是我们自己的解析器找错字段名，连续 13 天误报"某指标消失"（`私有事故档案`）。

> 注意同一份输出里的两件事：`源结构变化` 说这一列**在源层面**消失了，
> `field_gone` 是**源级**告警。如果只是某几个实体没有，那会是逐实体的 `field_disappeared`——
> 两条规则分工明确，不会对同一件事报两遍。

## 3. 第二件：+900% 需要你自己判是不是业务信号

```
2026-11-03  competitors:beta-gadget        value_swing:price      info
      price moved 99.0 -> 990.0 (+900%, threshold 30%)
```

> 上面这段与 §2 的同一行**逐字相同**，只是被单独摘出来强调——不是另一份输出。

工具把它标出来，而不是让你在图表上看到一个"暴涨 10 倍"然后直接去写分析。
**它不判断这是 bug 还是真涨价**——只把"跳了 900%"这件事和它的量级摆出来。这正是它该做的：
给证据，不给因果。

## 4. 然后才是提问（MCP）

前面两条是终端命令。要**提问**，接 MCP：

```bash
python scripts/mcp_server.py --db data/my.db        # stdio MCP 服务器
```

> ⚠️ 不带参数直接跑会进入 stdio 等待状态（等你发 JSON-RPC），**看起来像卡住**——这是正常的。
> 想人肉看输出，用上面第 2 步的 `audit_source.py`，或 `--selftest`。

在任何 MCP 宿主里，筛"价格 ≥ 50 的、按价格降序"：

```
search_records(source="competitors",
               filters=[{"field":"price","op":">=","value":50}],
               sort="price", desc=True)
```

返回 JSON（节选）：

```json
{"source": "competitors", "date": "2026-11-04", "total_matched": 2,
 "records": [{"entity": "beta-gadget", "fields": {"price": {"num": 990.0, ...}}},
             {"entity": "acme-widget", "fields": {"price": {"num": 58.0, ...}}}]}
```

> **缺席字段永不满足比较**。如果你筛 `stock_status == "in_stock"`，第 3–4 天会返回 0 行——
> 因为那两天这个字段根本没被抓到，而不是"没有一件在库"。**缺失 ≠ 0**，在查询层就成立。

## 5. 这套东西到底给了你什么

| 你平时要自己做的事 | 这里怎么做 |
|---|---|
| 逐列检查今天抓全了没有 | `audit_source.py` / `audit_field_coverage`：覆盖率 + `ABSENT-NOW` / `PARTIAL-DROP` |
| 写规则找异常 | 自动跑：累计量回退 / 身份突变 / 数值摆动 / 时间戳过期 / 字段突然缺席 / 整条记录消失 / 文本漂移 / 源改版（加列·减列·改名） / 抓取断档 |
| 事后想不起来某个数从哪来 | 每个事实带 `raw_ref` 指回原始文件 |
| 换了个数据源要重写一套 | 换 `--source` 与 `source.json` 就行，同一套检测与 MCP |
| 缺的数据被当成 0 | 缺席字段不落库、不参与比较、显示为缺席 |
| 两次抓取之间到底变了什么 | `diff_snapshots`：新增 / 消失 / 逐字段变化 |

## 6. 想让它更懂你的数据（可选）

在导出目录放一个 `source.json`：

```json
{
  "entity_column": "product",
  "monotonic_fields": ["units_sold"],
  "identity_fields": ["seller_name"],
  "track_text_fields": ["title", "status"],
  "swing_threshold": 0.3,
  "stale_hours": 48,
  "max_gap_days": 7,
  "min_presence_days": 2,
  "null_markers": ["N/A", "-", ""]
}
```

- `monotonic_fields`：只增不减的量（累计安装、累计销售额）→ 回退即异常；
- `identity_fields`：判断"还是不是同一个实体"（**填所有者/卖家/公司名这类列，不要填实体列本身**——实体列不进事实表，填了等于没配）；
- `track_text_fields`：哪些**文本列**的内容变化值得记一条异常（不填就完全不检测文本变化）；
- `max_gap_days`：抓取断档的容忍阈值（本就周更/月更时设大一点）；
- `min_presence_days`：整条记录消失、或某列消失，要连续出现几天才报警（默认 **3**）；
- `null_markers`：哪些写法算"没有值"（**不是 0**）。

完整字段说明见 [ADAPTERS.md](ADAPTERS.md)。
