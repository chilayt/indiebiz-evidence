# 交接记录 · 2026-11-13 · PyPI 发布成功（v0.6.1）

| 项 | 内容 |
|---|---|
| 里程碑 | **indiebiz-evidence 0.6.1 已发布到 PyPI**，任何人可 `pip install indiebiz-evidence` |
| PyPI 页 | https://pypi.org/project/indiebiz-evidence/0.6.1/ |
| 验证 | 全新 venv 从 PyPI 安装 0.6.1，仓库外 demo + 12 工具 selftest 全过 |
| 账户 | 负责人用 iCloud 邮箱注册（非 Gmail，故 Gmail 无验证信），已验证 + 已开 2FA（TOTP）|
| token | indiebiz-upload，Entire account scope；存 I:\tools\DSH\credentials\pypi-token.txt/.md（不进 git）|

## 过程要点
- 负责人浏览器已登录；用 browser-skill 协助走完 2FA（恢复码由负责人自存，我不读）+ 建 token。
- token 只显示一次，负责人一度切走页面丢失显示，后自行找回并贴给我。
- twine check 两包 PASSED → twine upload 成功（TWINE_USERNAME=__token__）。
- 安全：token 不经浏览器抓取，由负责人显式提供；存本机凭据目录，未提交。

## 下一步（可选）
- **MCP Registry**：server.json 已备好（pypi/stdio/uvx），README 已含 mcp-name 标记且已随包上 PyPI。
  需 mcp-publisher CLI + 负责人 GitHub OAuth（chilayt）。官方 registry 仍 preview。
- 低门槛目录站（mcp.so / glama 等）可先提交。
- 真实语料精度验证仍未完成（COMPLIANCE）。