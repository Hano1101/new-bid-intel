# 招采数据智能分析引擎

面向政府采购公告的模型主导抽取、关系建模与可核验分析平台，对应赛题五“面向行业数据的智能实体挖掘与关系建模”。系统从公告 HTML、压缩包和附件中抽取标的物七字段、采购单位、投标主体和中标结果，并提供五类关系查询、图谱分析和人工核验工作台。

**从材料到核查结果，一套工作台完成。** 复杂附件自动解析，结果可回查原文；主体关系可搜索、可解释；人工复核保留理由和历史；公告变化可比较版本。批量任务支持有界并发、检查点和暂停续跑。

评审演示入口见 [评委操作指南](docs/REVIEWER_GUIDE.md)；系统报告、演示材料和资料包说明见[初赛交付索引](deliverables/README.md)。

## 功能概览

| 能力 | 说明 |
|---|---|
| 公告抽取 | `rules`、`hybrid`、`model` 三路线处理 HTML 与附件，并保留候选来源、证据和解析 warning。 |
| 关系分析 | 提供五类采购查询；分析 API 可选 SQLite/Neo4j，关系图浏览使用 SQLite 投影。 |
| 复核与追踪 | 提供人工标注、候选复核、关系线索、公告与附件版本比较。 |
| 批量处理 | 后台任务提供有界并发、检查点、暂停续跑、失败重试和数据集隔离。 |
| 本地评测 | 24 条 reviewed 数据已参与开发调试，只能作为本地回归材料，不是独立测试集或官方成绩。 |

## 文档导航

| 文档 | 用途 |
|---|---|
| [`docs/REVIEWER_GUIDE.md`](docs/REVIEWER_GUIDE.md) | 离线启动、登录和功能演示 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 环境安装、运行、测试、故障排查和 Git 工作流 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 系统数据流和组件边界 |
| [`docs/MODEL_AND_EXTRACTION.md`](docs/MODEL_AND_EXTRACTION.md) | 抽取路线、证据和包号规则 |
| [`docs/DATA_INTAKE.md`](docs/DATA_INTAKE.md) | 数据导入、附件处理和质量边界 |
| [`docs/QUERY_SEMANTICS.md`](docs/QUERY_SEMANTICS.md) / [`docs/EVALUATION.md`](docs/EVALUATION.md) | 查询口径与本地评测定义 |
| [`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) | 全部操作手册、评测和交付文档 |

[`deliverables/`](deliverables/README.md) 提供系统设计、技术路线、数据质量三份 Word/PDF 报告及 Markdown 源稿，同时提供 PPT 内容大纲和两类视频脚本。

## 快速启动

### 安装

```powershell
cd backend
# 以下以 Python 3.13 为例；若本机没有 3.13，请改为已安装的 3.12 或 3.11。
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,ocr,graph]"
Copy-Item .env.example .env

cd ..\frontend
npm ci
```

Python 版本支持 3.11–3.13。`scripts/Start-Demo.ps1` 会按 3.13、3.12、3.11 的顺序自动选择已安装版本；手动初始化时将示例命令中的版本号替换为本机可用版本。旧 DOC 需要 LibreOffice；Neo4j 只在启用图数据库后需要 Docker Desktop。

### 开发运行

```powershell
# 终端 A
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# 终端 B
cd frontend
npm run dev
```

打开 `http://localhost:5173`，API 文档为 `http://127.0.0.1:8000/docs`。Windows 离线演示可以使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Configure-ReviewerAccount.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\Start-Demo.ps1 -Offline
powershell -ExecutionPolicy Bypass -File .\scripts\Stop-Demo.ps1
```

离线数据集是虚构样例，只用于展示流程，不能用于比赛评分。局域网演示可使用启动脚本输出的主机地址；实际访问取决于部署网络、防火墙和访问策略，配置说明见 [`docs/LAN_ACCEPTANCE.md`](docs/LAN_ACCEPTANCE.md)。

## 模型配置

模型配置可以在网页“模型配置”面板填写，也可以放在 `backend/.env`：

```dotenv
MODEL_BASE_URL=https://your-openai-compatible-endpoint/v1
MODEL_NAME=deepseek-your-approved-model
MODEL_API_KEY=只保存在本机
```

只使用赛事允许的 Qwen/DeepSeek 资源，并记录版本、参数规模和资源来源。单条导入默认使用 `hybrid`；后台任务可选择 `rules`、`hybrid` 或 `model`。规则路线是可复现基线和离线兜底，不能代替模型路线的比赛合规说明。详见 [`docs/MODEL_AND_EXTRACTION.md`](docs/MODEL_AND_EXTRACTION.md)。

## Neo4j（可选）

```powershell
cd backend/neo4j_runtime
docker compose up -d
```

在 `backend/.env` 设置 `ANALYTICS_BACKEND=neo4j`、`NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD` 和 `NEO4J_DATABASE`。五类分析 API 会使用 Neo4j；连接失败时按请求回退 SQLite，并在响应头和前端显示实际后端。`/api/v1/graph` 的可视化投影仍使用 SQLite。完整说明见 [`backend/neo4j_runtime/README.md`](backend/neo4j_runtime/README.md)。

## API

后端启动后可在 `http://127.0.0.1:8000/docs` 查看 OpenAPI 文档。业务数据接口支持 `X-Dataset-ID` 隔离；模型配置、标注 Gold 和评测运行目录分别管理，不随业务数据集切换。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
cd ..\frontend
npm test
npm run build
```

本地指标定义和三路线回归步骤见 [`docs/EVALUATION.md`](docs/EVALUATION.md) 与 [`docs/benchmarks/route-evaluation-runbook.md`](docs/benchmarks/route-evaluation-runbook.md)。历史查询 oracle 和跨后端对照属于不同日期、口径与运行范围，不能合并为一个分数；对应材料见[归档索引](archive/README.md)，当前查询语义见 [`docs/QUERY_SEMANTICS.md`](docs/QUERY_SEMANTICS.md)。

## 评测口径

24 条本地 reviewed 数据已参与开发调试，只作为本地回归材料，不是独立测试集或官方成绩。全量处理数量和附件解析覆盖用于描述工程流程，不等于字段准确率；指标定义与数据范围见 [`docs/EVALUATION.md`](docs/EVALUATION.md) 和 [`docs/DATA_INTAKE.md`](docs/DATA_INTAKE.md)。

## 许可证

仓库尚未声明开源许可证；复用和再分发前需由项目负责人确定并添加 `LICENSE`。

## 贡献与安全

贡献流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，敏感信息处理见 [`SECURITY.md`](SECURITY.md)。提交前请执行 [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)，不要提交密钥、原始官方材料或本地 `.data`。
