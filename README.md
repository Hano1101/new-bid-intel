# 招采数据智能分析引擎

面向政府采购公告的模型主导抽取、关系建模与可核验分析平台，对应赛题五“面向行业数据的智能实体挖掘与关系建模”。系统从公告 HTML、压缩包和附件中抽取标的物七字段、采购单位、投标主体和中标结果，并提供五类关系查询、图谱分析和人工核验工作台。

**从材料到核查结果，一套工作台完成。** 复杂附件自动解析，结果可回查原文；主体关系可搜索、可解释；人工复核保留理由和历史；公告变化可比较版本。批量任务支持有界并发、检查点和暂停续跑。

第一次了解作品，先看 [评委快速了解](docs/JUDGE_QUICKSTART.md)；需要完整材料，进入 [初赛报告与演示索引](deliverables/README.md)。

## 当前状态

| 能力 | 状态 |
|---|---|
| 任务一：七字段、主体、中标结果抽取 | rules / hybrid / model 三路线已实现；24 条本地 reviewed 数据已用于三路线开发回归 |
| 任务二：五类关系查询与金额汇总 | SQLite 已验收；Neo4j 可选后端已接入并可回退 SQLite |
| 任务三：导入、检索、分析、图谱投影、标注工作台 | 已实现；演示服务支持局域网部署配置 |
| 附件处理 | HTML、DOC/DOCX、XLS/XLSX、PDF、图片/OCR、RAR/7z 及失败隔离已接入 |
| 后台任务 | 检查点、暂停、续跑、失败重试、损坏结果恢复和数据集隔离已实现 |
| 评测状态 | 24 条本地 reviewed 数据已完成 rules/hybrid/model 回放；该集合已用于开发和调试，不是独立测试集或官方成绩 |

当前验证基线（提交 `c1fc4c4`）：后端 `662 passed, 7 skipped, 2 warnings`，Ruff 通过，前端 `80 passed`，生产构建通过但有大 chunk 警告。Neo4j、LibreOffice 和部分 Windows 符号链接测试按环境可选启用。本地 24 条 reviewed 数据已参与调试，指标按开发回归口径报告，不是官方成绩。

## 文档导航

| 文档 | 用途 |
|---|---|
| [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | 接手项目、历史决策和操作红线 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 数据流、组件边界、SQLite/Neo4j 和后台状态机 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 环境安装、运行、测试、故障排查和 Git 工作流 |
| [`docs/MODEL_AND_EXTRACTION.md`](docs/MODEL_AND_EXTRACTION.md) | 三种抽取路线、模型契约、证据和包号限制 |
| [`docs/MODEL_ENDPOINT_ACCEPTANCE.md`](docs/MODEL_ENDPOINT_ACCEPTANCE.md) | 换 Qwen/DeepSeek 端点、资源合规和故障验收 |
| [`docs/DATA_QUALITY.md`](docs/DATA_QUALITY.md) | 官方附件统计、warning、OCR 和人工复核边界 |
| [`docs/DATA_INTAKE.md`](docs/DATA_INTAKE.md) | 官方数据接入、附件解析、后台批处理和数据集切换 |
| [`docs/QUERY_SEMANTICS.md`](docs/QUERY_SEMANTICS.md) | 五类查询及金额统计口径 |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Gold schema、本地指标与评测约束 |
| [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) | 比赛提交、评审演示和发布前检查 |
| [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) | 当前唯一的缺口和优先级事实来源 |
| [`docs/REVIEWER_GUIDE.md`](docs/REVIEWER_GUIDE.md) | 评审登录、演示和局域网操作 |
| [`docs/ANNOTATION_ANNOTATOR.md`](docs/ANNOTATION_ANNOTATOR.md) | 队友标注员操作卡 |
| [`docs/INNOVATION_ROADMAP.md`](docs/INNOVATION_ROADMAP.md) | 面向采购甲方的创新功能顺序、依赖和验收标准 |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | 历史决策、验收范围和实测数字 |
| [`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) | 工程文档和比赛交付源稿总索引 |

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

## API 概览

- `GET /api/v1/health`：健康检查。
- `GET/PUT /api/v1/model-config`、`POST /api/v1/model-config/test`：读取、保存和探测模型配置（Key 只显示打码值）。
- `POST /api/v1/notices/import`、`POST /api/v1/notices/import-batch`：单公告/批量导入。
- `GET /api/v1/notices/{notice_id}`：只读公告详情，返回已保存的候选、关系、来源位置、字段来源片段、字段状态、文件哈希和解析警告；旧记录缺证据时标为未知/待核验，不回填推断值。
- `GET/POST /api/v1/jobs`：创建、查看、暂停、续跑和报告后台任务。
- `GET /api/v1/items`、`GET /api/v1/organizations`：检索候选和主体。
- `GET /api/v1/analytics/buyers/{buyer_id}/awardees`：场景一。
- `GET /api/v1/analytics/buyers/{buyer_id}/bidders`：场景二。
- `GET /api/v1/analytics/suppliers/{supplier_id}/co-bidders`：场景三。
- `POST /api/v1/analytics/common-buyers`、`POST /api/v1/analytics/common-projects`：场景四、五。
- `POST /api/v1/controlled-query/parse`、`POST /api/v1/controlled-query/execute`：五场景白名单内的自然语言意图解析与只读执行；模型端点可按赛事提供的兼容 API 配置切换。
- `GET /api/v1/analytics/relation-clues`：按数据集返回带来源证据的待核查关系线索，当前使用 SQLite。
- `GET /api/v1/evaluation/schema`、`POST /api/v1/evaluation/draft`、`POST /api/v1/evaluation/run`：标注和本地评测。
- `GET /api/v1/graph`：SQLite 图谱可视化投影。

所有业务请求可通过 `X-Dataset-ID` 选择隔离数据集。模型配置、标注 Gold 和评测运行目录分别管理，不会因为业务数据集切换而混用。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
cd ..\frontend
npm test
npm run build
```

本地评测方法与三路线回归运行说明见 [`docs/EVALUATION.md`](docs/EVALUATION.md) 和 [`docs/benchmarks/route-evaluation-runbook.md`](docs/benchmarks/route-evaluation-runbook.md)。24 条 reviewed 数据已参与开发调试，用于回归和路线诊断；本地指标不是官方评分结果。历史 SQLite/Neo4j 双后端与新答疑口径 SQLite oracle 均有 `6471/6471` 记录，二者运行范围不同；Neo4j 另通过真实集成测试。范围说明见 [`docs/QUERY_SEMANTICS.md`](docs/QUERY_SEMANTICS.md)。

## 已知限制

- 官方没有逐条 ground-truth，因此 1038 条全量入库、候选数量、OCR覆盖率和查询可运行性都不能直接转换成准确率。
- 24 条 reviewed 数据已完成三路线本地回放，作为工程回归和演示证据；其已用于开发调试，不是独立测试集。赛事平台按自身评分基准给出正式成绩，本地数字不替代官方成绩。
- 87 个无效下载响应、19 个程序解析失败和 7 个不支持格式已隔离并保留来源，缺失源文件不能靠模型恢复。
- 名称型包号需要明确标签和值的连续证据；证据不足时保留 `default`，可能影响包级对齐和包级统计。
- `/api/v1/graph` 仍是 SQLite 投影，Neo4j 只控制五类分析 API。
- 当前仓库尚未声明开源许可证；公开再分发前请先添加明确的 `LICENSE`。

## 贡献与安全

贡献流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，敏感信息处理见 [`SECURITY.md`](SECURITY.md)。提交前请执行 [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)，不要提交密钥、原始官方材料或本地 `.data`。

## 许可证

本仓库当前未声明许可证。除非项目负责人补充 `LICENSE`，否则不要把代码宣传为可自由复制、修改或再分发。
