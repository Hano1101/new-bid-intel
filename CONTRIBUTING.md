# 贡献指南

## 开始前

先读仓库 [README](README.md) 的文档导航和 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)，再阅读本次改动涉及的架构、数据、模型或评测说明。不要提交 API Key、评审密码、原始官方材料、`.data`、数据库或本机模型缓存。

## 提交改动

- 一个改动聚焦一个可验收主题，提交标题用简短动词，例如 `fix:`、`feat:`、`docs:`。
- 解析、模型、查询或数据口径变化须同步更新相关测试和当前维护文档；历史归档只在补正史料错误或补齐对应时间点的证据时更新。
- 评测结果说明 Gold 版本、数据集角色、公告范围、profile、代码与模型配置，并区分历史快照与本次运行。
- 24 条 reviewed 数据已参与调试，只能标为本地开发回归材料；不得将它写成独立 holdout、官方 ground-truth 或官方准确率。

## 提交前检查

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
cd ..\frontend
npm test
npm run build
cd ..
git diff --check
```

PR 或交接说明写清问题、行为变化、验证命令、样本/环境范围和已知限制。涉及真实模型请求时说明请求数、失败数和是否产生费用。
