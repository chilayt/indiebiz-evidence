# 发布指南（让工具能被装上、被发现）

> 目标：`pip install indiebiz-evidence` 对任何人可用 + 进入 MCP 用户会逛的目录。
> 下面第 1、2 步需要**负责人的账号/凭据**，维护者不能代登。材料已备好。

## 已就绪（维护者已做）
- PyPI 名字 `indiebiz-evidence` 已查**可用**（未被占用）。
- 包元数据齐全：classifiers / keywords / URLs；`requires-python >=3.11`；零依赖。
- `dist/` 已构建 sdist + wheel，并在**全新 venv、仓库外**验证可装可跑（demo + 12 工具 selftest）。
- README 已含 MCP Registry 所有权验证标记 `<!-- mcp-name: io.github.chilayt/indiebiz-evidence -->`。
- `server.json` 已按官方 schema 备好（registryType=pypi, transport=stdio, runtimeHint=uvx）。

## 第 1 步：发布到 PyPI（需负责人 PyPI 账号）

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

## 第 2 步：发布到官方 MCP Registry（需负责人 GitHub 认证）

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

一些目录站只需 GitHub 仓库 URL 即可收录/抓取，门槛比官方 Registry 低，可先做：
- mcp.so、glama.ai/mcp、smithery.ai 等（提交前先确认各自当前收录规则）。
- 提交材料：仓库 URL + 一句话定位 + 安装/启动方式（`pip install indiebiz-evidence` → `indiebiz-evidence mcp`）。

## 诚实性提醒
- 本工具是**实验性**（0.6.x），真实语料精度验证未完成；对外文案不要声称"生产级精度"。
- 不刷 star/下载量；目录提交是"放到用户会看的地方"，不是制造虚假热度。