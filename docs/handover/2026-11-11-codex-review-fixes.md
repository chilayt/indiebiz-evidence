# 交接记录 · 2026-11-11 · Codex 阶段1复核后的修复（v0.5.6）

| 项 | 内容 |
|---|---|
| 复核任务 | `cmwbpa1za`（Codex 复核 `1cac572..52909c9`） |
| 复核结论 | 部分通过；**反对默认空重导清空**；暂不建议立即转 public |
| 修复后 SHA | `dbabf07`，tag v0.5.6，Release 已建 |
| CI | 9/9 全绿（含增强的安装验收：真控制台命令 + 仓库外真 stdio 握手） |

## 按 Codex 裁决执行的修复
1. **空重导默认拒绝破坏性替换**（`--allow-empty-replace` 才清）；判断基于解析后可用事实数。C-SPEC 本就允许'清空或拒绝'。
2. **修'报失败但已提交删除'**：CLI 不再因 facts==0 提前 exit 3 跳过检测。
3. **空批次可见**：list_sources 加 latest_capture_date/latest_fact_date/latest_capture_empty；审计显式提示空批次+参照日。
4. **修空转测试 C03**：diff 断言原在实体层找 field（实际嵌套 changes）且不跨边界→从没执行；现真查并变异验证。
5. **selftest 补 UTF-8**（CP936+emoji 曾崩）。
6. **依赖守卫按 3.11+ 简化**（删回退+3.9 模拟测试）。
7. **安装验收增强**：真控制台命令 + 真 stdio 握手。

## OpenAI「Codex for Open Source」（Codex 已核实官方要求）
- **仓库必须 public**，GitHub 个人资料也须公开；申请表 openai.com/form/codex-for-oss
- 官方确认送 **6 个月 ChatGPT Pro（含 Codex）**；无固定 star 门槛；API credits/Security 另行评估不保证
- 早期项目可申请，但要用生态价值说服，**测试数不能替代采用证据**
- 英文申请材料已备好（见 采集/OPENAI-OSS-申请.md）；资格说明/API用途/补充说明各 ≤500 字符
- **插件目录渠道**：本地 MCP 提交目前**仅面向获批合作方**（需 OpenAI 联系人加白名单），当前不可直接提交

## 需要负责人亲自做
1. 决定是否转 public（承担公开整个 git 历史+Release 的决定）；当前文件检查≠完整历史凭证审计
2. 公开 GitHub 个人资料；转公开后启用并核验 SECURITY.md 承诺的私密漏洞报告入口
3. 提供本人姓名/ChatGPT 邮箱/维护者角色/Organization ID，确认权益与用途
4. 亲自填表、接受条款、完成身份/仓库控制权核验

## 遗留
- 真实语料精度审计仍未做（路线图第5步）。Codex 认为实验性版本可不等它转公开，但这是负责人的决定。
- 转 public 前建议做一次完整 git 历史凭证审计（不只当前文件）。