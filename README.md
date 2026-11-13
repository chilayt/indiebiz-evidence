# indiebiz-evidence

<!-- mcp-name: io.github.chilayt/indiebiz-evidence -->

> **English** — You collect information from several sources. Before you present a number
> as "the answer", you need to know: do the sources agree? Can you trace it back to the raw
> file? Is it even still being reported? indiebiz-evidence is a local, zero-dependency
> evidence layer that **cross-checks what you collected** — agreement across sources,
> provenance, and anomalies — so you verify before you conclude. It does not collect for
> you; it helps you verify what you collected — equal values are not proof of truth. Point it at dated CSV/JSON exports and query
> it from the CLI or a zero-dependency MCP server your agent can call.

你从好几个来源收集信息。但在把一个数字当成"答案"给出去之前，你得先知道：**这几个来源说的
一致吗？能不能回溯到原始文件？它现在还在被报告吗？** indiebiz-evidence 是一个本地、零依赖的
证据层，把你收集到的东西**交叉复核**——多源是否一致、出处可回溯、异常先声明——让你**先核实，
再下结论**。它不替你采集，它帮你**核实**采到的东西——值相同不等于事实已核实。指向按日期命名的 CSV/JSON 导出即可，CLI 或
零依赖 MCP Server 供你的 agent 调用。

## 它解决的不是"抓不到"，是"没复核就当成正确答案"

做信息收集的人最容易翻的车，不是抓取失败，而是**复核不完全就把一个值当成了事实**：

| 翻车方式 | 后果 | 这里的做法 |
|---|---|---|
| 某个字段**悄悄不再输出**（页面改版） | 你以为"上游没这个数据了"，或根本没注意 | `audit_field_coverage` 逐字段给覆盖率，并在"以前有、最新没有"时判 `absent_on_latest`，**先怀疑自己的抓取器** |
| 某条记录**整条消失**（下架/招满/撤稿） | 被当成"数据没抓到"或直接漏看 | `entity_disappeared`，并明确写"下架和漏抓从这里看一样，两处都要查" |
| 抓取**停了 30 天**，两个点被当成"隔了一天" | 每个指标都像一夜暴涨 | 学习该源自己的节奏；跨断档的变化明写跨度（如 `over 30 days`），不伪造精度 |
| **一个来源给了个数，你就信了** | 孤证当事实；其实另一个源说的不一样 | `cross_check` 把同一实体在**所有来源**的值摆一起：一致 / 打架 / 孤证，各带出处，让你判断而不是替你宣判 |
| 同一个东西**三种写法**拼不起来 | 三个实体，永远对不上 | `resolve_entities` / `find_duplicate_entities` 给**候选和证据**，绝不自动合并 |
| 缺失字段被当 0 | 有收入的项目被判成"零收入" | 缺席不落库、不参与比较、显示为缺席——**在查询层就成立，不靠你记得** |

## 五分钟上手（先跑 demo，不用先有自己的数据）

```bash
pip install .                              # 零运行时依赖
indiebiz-evidence demo --db demo.db        # 合成数据，立刻看到 6 类异常
indiebiz-evidence audit --db demo.db --source demo-prices   # 一句话健康报告
indiebiz-evidence mcp --db demo.db --selftest               # 12 个 MCP 工具自检
```

demo 用的是 2099 年的虚构实体，**不需要你先准备任何数据**。装完在任意目录都能跑
（演示数据随包分发，不依赖仓库目录）。

**用你自己的数据**：把按日期命名的 CSV/JSON 导出放进一个目录，然后

```bash
indiebiz-evidence import --source competitors --input ./my-exports --db data/my.db
indiebiz-evidence audit --db data/my.db --source competitors
```

> **路径规则**：`--input` / `--db` 都相对**当前工作目录**解析（和任何普通 CLI 一样）。
> 相对路径找不到时，import 会明确报错退出，不会静默建一个空库。

**从多个来源核实一条信息**（这是本工具的核心用途）：把不同来源的导出分别导入成不同的源，
然后对同一个实体做跨源核对——

```bash
indiebiz-evidence import --source site-a --input ./from-site-a --db data/my.db
indiebiz-evidence import --source site-b --input ./from-site-b --db data/my.db
indiebiz-evidence crosscheck --db data/my.db --entity "Acme Widget"
```

它会把 `Acme Widget` 在 site-a / site-b 的每个字段摆到一起，告诉你：

- **一致**：几个来源说的相同（值与原文都一致）→ 有佐证，但仍需确认实体/口径/时效/来源独立；
- **打架**：来源之间不同 → 列出各自的值和出处，**先查是不是口径/单位/抓取日期不同，再下结论**；
- **孤证**：只有一个来源报告 → 没法交叉验证，别当成已核实。

每条观测都带自己的原文、抓取日和 `raw_ref` 能回溯；某源没报的字段记为"未报告"，**不是 0**。名字匹配只是线索，
字段同名也不代表同口径——所以它**摆证据给你判断，不替你宣判谁对谁错**。

**一个 30 秒的真实感示例**（三源抓价，揪出小数点错误/悄悄丢列/孤证）：
[examples/cross_check_prices](examples/cross_check_prices/README.md)，`python examples/cross_check_prices/run_example.py` 直接跑。

更完整的四天踩坑教程见 [**docs/QUICKSTART-COLLECTOR.md**](docs/QUICKSTART-COLLECTOR.md)，
**每一段输出都是照抄实跑结果**（CI 机制保证它不会漂移）。仓库内也可用
`python scripts/make_demo_db.py` / `run_import.py` / `audit_source.py`（与安装版等价）。

## 接进你的 agent（MCP 宿主配置）

MCP server 走 stdio。在宿主（Claude Desktop、Codex 等）的配置里加一段，
**用绝对路径**指向解释器和数据库：

```json
{
  "mcpServers": {
    "indiebiz-evidence": {
      "command": "indiebiz-evidence",
      "args": ["mcp", "--db", "/absolute/path/to/data/my.db"]
    }
  }
}
```

若宿主找不到 `indiebiz-evidence` 命令，把 `command` 换成解释器绝对路径、
`args` 换成 `["-m", "indiebiz_evidence.cli", "mcp", "--db", "..."]`。
配置后重启宿主，先调 `list_sources` 确认连上了。

## 十二个 MCP 工具

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
| `cross_check` | **跨源核对**：同一实体在所有来源的值摆一起，判 一致/打架/孤证，各带出处；同名≠同口径，只摆值不宣判 |
| `list_source_anomalies` | 检测到的异常：数值摆动、累计回退、字段/实体消失、文本漂移、源改版、抓取断档 |

工具描述里写死了纪律：**孤证不是核实；解读任何变化前先查异常；缺失≠0；不跨身份边界做差；跨断档的变化不是一夜之间的；候选不是结论。**

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

**v0.5.x 是实验性版本**。已用：合成回归矩阵（13 场景）、147 项测试、文档真值检查。
**未用真实语料验证精度**——这条缺口写在 [COMPLIANCE.md](COMPLIANCE.md) §六，不藏着。
适用场景：本地、受信任输入、单机使用。不承诺处理任意规模或敌意输入。

## 安装

```bash
pip install .                          # 零运行时依赖，装出 indiebiz-evidence 命令
python scripts/run_release_gate.py     # 五道门禁单一入口（147 tests，跳过=失败；CI 同款）
```

## 数据与隐私

**本仓库不含任何上游数据**：没有数据库、没有抓取内容、没有真实实体名。demo 全部是 2099 年的虚构实体。
`data/` 全目录 gitignored。详见 [COMPLIANCE.md](COMPLIANCE.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
