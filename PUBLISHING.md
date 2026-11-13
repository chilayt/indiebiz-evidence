# 发布指南（让工具能被装上、被发现）

> 目标：`pip install indiebiz-evidence` 对任何人可用 + 进入 MCP 用户会逛的目录。
> 下面第 1、2 步需要**负责人的账号/凭据**，维护者不能代登。材料已备好。

## 已就绪（维护者已做）
- PyPI 名字 `indiebiz-evidence` 已查**可用**（未被占用）。
- 包元数据齐全：classifiers / keywords / URLs；`requires-python >=3.11`；零依赖。
- `dist/` 已构建 sdist + wheel，并在**全新 venv、仓库外**验证可装可跑（demo + 12 工具 selftest）。
- README 已含 MCP Registry 所有权验证标记 `<!-- mcp-name: io.github.chilayt/indiebiz-evidence -->`。
- `server.json` 已按官方 schema 备好（registryType=pypi, transport=stdio, runtimeHint=uvx）。

## 第 1 步：发布到 PyPI ✅ 已完成（2026-11-13，v0.6.1）

> 已发布：https://pypi.org/project/indiebiz-evidence/0.6.1/ ；全新 venv `pip install indiebiz-evidence` 验证可装可跑。token 存于本机凭据目录（不进 git）。以下为原步骤存档：

1. 注册/登录 https://pypi.org ，开启 2FA。
2. Account settings → API tokens → 新建 token（首次上传用 "Entire account"  scope；上传后可换成仅该项目）。
3. 上传（在本仓库根目录）：
   ```bash
   python -m pip install --upgrade twine
   python -m build                 # 重新生成 dist/（含最新 README 的 mcp-name 标记）
   python -m twine upload dist/*   # 用户名填 __token__，密码填 pypi- 开头的 token
   ```
4. 验证：`pip install indiebiz-evidence` 在干净环境能装。

> ⚠️ PyPI 版本号**不可覆盖**：发错的版本只能再发新版，不能改。当前待发版本 0.6.1。
> ⚠️ 上传前确认 `dist/` 里只有本次要发的版本，别把旧版本一起传上去。

## 第 2 步：发布到官方 MCP Registry ✅ 已完成（2026-11-13）

> 已发布：`io.github.chilayt/indiebiz-evidence@0.6.1`，registry 搜索可查到。mcp-publisher 装于 I:\tools\mcp-publisher\；GitHub 设备码授权由负责人完成。description 限 100 字符、packageArguments 需 positional 对象，均已处理。以下为原步骤存档：

前提：第 1 步已把包发到 PyPI（Registry 靠 README 里的 `mcp-name` 标记验证 PyPI 所有权）。
Registry 目前是 **preview**，可能有破坏性变更。流程见官方 quickstart：
https://modelcontextprotocol.org/registry/quickstart

```bash
# 安装 mcp-publisher（按官方 quickstart 的方式）
mcp-publisher login github     # 走 GitHub OAuth，用负责人账号（chilayt）
mcp-publisher publish          # 读取本仓库 server.json 并发布
```

- server name 为 `io.github.chilayt/indiebiz-evidence`，与 GitHub 账号对应。
- 发布后，MCP 客户端/聚合器即可发现本 server；`runtimeHint=uvx` + `packageArguments=["mcp"]`
  表示以 `uvx indiebiz-evidence mcp` 启动（默认 db 为 data/evidence.db，可用 --db 覆盖）。

## 第 3 步（可选，低门槛）：提交到 MCP 目录站

> 主渠道（PyPI + 官方 MCP Registry）已通。目录站是额外搜索面，锦上添花。
> 2026-11-13 尝试用浏览器自动提交时会话持续掉线（bsk daemon/扩展版本错位），改为手动步骤如下。

已确认的收录规则：
- **mcp.so**：填 "Submit" 表单，提交仓库 URL（它从 GitHub + npm 抓取）。当前搜 indiebiz 为 0 结果，需提交。
  - 入口：https://mcp.so/submit ；填 GitHub 仓库 https://github.com/chilayt/indiebiz-evidence
- **Glama**（glama.ai/mcp/servers）：**自动发现** GitHub 公开 MCP 仓库；也可 submit/claim 补充元数据。仓库已公开，可能稍后自动收录。
- **PulseMCP**（pulsemcp.com）：填 "Add a server" 表单，提交仓库 URL。
- **Smithery**（smithery.ai）：需要 smithery.yaml 启动配置，偏托管/启动平台，门槛稍高，可后置。

提交材料（通用）：
- 仓库 URL：https://github.com/chilayt/indiebiz-evidence
- 一句话定位：Cross-check collected data across sources, with provenance, before trusting it. Zero-dependency MCP server.
- 安装/启动：pip install indiebiz-evidence → indiebiz-evidence mcp --db <path>
- PyPI：https://pypi.org/project/indiebiz-evidence/
- 官方 Registry：io.github.chilayt/indiebiz-evidence

> 诚实性：目录提交是"放到用户会看的地方"，不刷 star/下载量；不声称生产级精度。

## 诚实性提醒
- 本工具是**实验性**（0.6.x），真实语料精度验证未完成；对外文案不要声称"生产级精度"。
- 不刷 star/下载量；目录提交是"放到用户会看的地方"，不是制造虚假热度。