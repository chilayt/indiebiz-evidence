# COMPLIANCE · 定位、分发边界与上游数据注意

> 本文件描述**可验证的分发边界**与**已核验的上游条款事实**，不构成法律意见。内部决策记录不随仓库分发。

## 一、分发边界

**随仓库发布**：解析/存储/检测/报告代码、MCP 服务器、合成演示 fixtures（2099 年虚构实体）、方法论文档（PATTERNS / ADAPTERS / incidents，均已化名与数值合成化）。
**永不发布**：任何真实抓取数据（`data/` 全目录 gitignored）；本机配置；预置数据库；托管服务；抓取/爬虫代码；**TrustMRR 垂直 adapter（见 §三裁定）**。

## 二、筛选能力门禁（默认关闭）

TrustMRR 定向筛选（金矿/六排除/筛选参数/candidates 报告/简报 §五）代码级默认关闭（`screening_enabled`）；关闭时工具发现不展示参数、调用返回 policy error、输出无派生字段。审计能力（口径拆分、源健康、身份边界、证据链、七项审计统计）不受门禁影响。

## 三、上游条款重验结论（2026-11-07 实读 trustmrr.com/terms，页面标注 Last updated: November 2, 2026）

已核验的关键原文（§9 API 条款，摘录供核对）：

- **§9.1 允许**："…private acquisition research, **internal analysis, and internal tools** that help an authorized user evaluate startups."
- **§9.2**："An API key does not grant a license to **publish, index, sublicense, sell, redistribute**, or make TrustMRR data available to third parties… requires TrustMRR's prior written permission."
- **§9.3 禁止**（"use the API, directly or indirectly"）：
  - "Build, market, or operate a **product or workflow** that identifies successful startups so users can copy…; Offer or promote … **substantially similar tools based on TrustMRR data**"
  - "Scrape, harvest, **archive, or systematically reconstruct TrustMRR's database**; exceed documented limits; … combine multiple accounts, keys, IP addresses, agents, or services to bypass restrictions"
  - "Use API data to train, fine-tune, **ground**, evaluate, or populate an AI model, **dataset**, **search index**, recommendation system, or automated content generator **without prior written permission**"
  - "Attempt to **identify an anonymous or stealth startup**, infer hidden information…"

### 据此的三个裁定

1. **公开推送暂缓（本仓库）**：2026-11-02 版条款比发起团队 2026-10-09 的记录更严（新增 archive/systematically reconstruct、AI grounding/dataset/search index、workflow/tool promotion 三类措辞）。发布一个"从 TrustMRR .md 归档构建时序数据库"的垂直 adapter，即使不含数据、即使筛选关闭，也可能落入 §9.3 的 "workflow / substantially similar tools based on TrustMRR data"。**公开发布物必须先完成拆包：通用审计引擎（core + generic adapter + PATTERNS + incidents）公开；TrustMRR 垂直层（parser/backfill/detect 垂直规则/metrics/reports 垂直部分）转私有**，仅内部使用（§9.1 的 internal tools 允许用途）。拆包完成前 remote 保持为空。
2. **incidents/ 与 fixtures 全面合成化**：§9.2 限制再分发。事故档案改用化名与合成示意数值（量级与相对关系保留），原始证据经 raw_ref 存于发起方私有归档；合成 fixtures 承担全部对外可复现职责。
3. **匿名性纪律**：本项目的 slug 复用检测只标注"对比边界"，**从不尝试去匿名化**（§9.3 禁止项），此边界写进 detect 规则设计并有意保持。

### ⚠️ 内部采集管道的合规提示（已另行上报发起方负责人）

§9.3 的 archive/systematically reconstruct 与 AI grounding/dataset 条款同样指向**发起团队自己的每日全量抓取＋建库＋MCP 供 agent 查询**的实践（与 §9.1 "internal analysis/internal tools" 允许项存在张力，且 .md 公开页与 API 的适用边界条款未明说）。**裁定（2026-11-08，发起方负责人批准 B 案）**：每日抓取范围由全量（约 433 份）降为"策划追踪名单（约 60–100 个在研实体）+ 当日新面孔"，远离 systematic reconstruction 定性、贴近 §9.1 的 evaluating selected startups。**补充核查（同日）**：官方 llms.txt 明示 "Do not scrape the website for full marketplace access"（禁整站镜像）并将单个 {slug}.md 页指定为 AI-readable 公开通道；详情级数据另有免费认证通道（API key / 官方 MCP get_startup）。据此书面许可询问（D 项）撤回不发，改为 **E 案**：详情抓取迁移至官方认证 API/MCP（key 由负责人注册创建），迁移前 B 案名单制运行。**本仓库公开物不包含、也不鼓励任何抓取行为。**

## 四、License 与数据权利

代码以 **MIT** 发布：只授代码权，不授任何第三方数据权利，不构成上游授权，不对 §二门禁之外的用途背书。使用者导入自己数据前须自行核验其访问/处理/下游使用权限。

## 五、公开发布检查单（拆包后逐项核，绑定候选提交）

- [x] 定位与门禁（§二；TestMcpScreeningGate 三层覆盖）
- [x] 仓库无本机路径（.qoder-credits 已 untrack + gitignore + **历史净化**）
- [x] 上游条款重验（§三，2026-11-02 版实读）
- [x] incidents/fixtures 合成化（§三裁定 2）
- [ ] **core / TrustMRR-vertical 拆包**（§三裁定 1；公开仓仅含通用引擎）
- [ ] 候选提交绑定复验：对将推送的确切 commit 跑 run_tests（0 skip）/ run_precision_audit / demo+selftest（默认关闭态）/ pip 安装冒烟，记录提交号与退出码于发布日志
- [ ] 英文首屏（已完成）+ SECURITY.md 联系渠道填实
- [x] CONTRIBUTING.md / CHANGELOG.md / CI

## 六、公开前检查单（2026-11-10 更新）

- [x] **core / vertical 拆包**：本仓库只含通用引擎；垂直适配层（特定数据源的解析、报表、定向筛选）留在私有仓，不随本包分发。
- [x] **本仓不含上游数据**：无数据库、无抓取内容、无真实实体名；demo 全部为 2099 年虚构实体；`data/` 全目录 gitignored。
- [x] **文档真值机制**：`scripts/check_docs_are_true.py` 让文档里的输出块与真实运行一致，接入 CI。
- [ ] **通用层真实语料抽样**：`run_generic_precision_audit.py` 的 13 个合成场景是回归矩阵，不等于纪律 9 要求的"真实语料全量输出 + 抽样数误报"。缺语料时该脚本报 `incomplete`，不得算通过。
- [ ] SECURITY.md 联系渠道填实。
