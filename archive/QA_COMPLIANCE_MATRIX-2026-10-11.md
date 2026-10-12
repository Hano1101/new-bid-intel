# 赛题五 QA 合规矩阵（2026-10-11 历史快照）

> **历史快照。** 本文于 2026-10-12 移出当前文档入口；其中的状态、优先级、行号、指标和验收记录仅描述当时范围，不代表当前任务或成绩。当前项目说明见 [README](../README.md) 和 [文档导航](../docs/DOCUMENTATION_INDEX.md)；本归档目录见 [索引](README.md)。


更新日期：2026-10-11（当前验收：后端 662 passed、7 skipped、2 warnings；前端 80 passed 与构建通过；Ruff 通过）

本文依据赛题要求摘录、答疑记录、当前仓库代码和已有测试整理，用于说明作品功能如何对应题目要求。它是项目侧的实现证据矩阵，不代替评委评分。

## 使用边界

- 仓库中的 reviewed Gold 是团队人工核验的本地开发回归材料，已参与调试；用于检查工程行为，不作为独立泛化结论。
- mock 模型测试只验证适配器、错误处理和 schema 保护，不代表真实 Qwen/DeepSeek 的抽取准确率。
- 赛题答疑没有覆盖的事项不在本文擅自补充为“官方口径”；此类事项标明当前团队采用的可复现解释。
- “已实现”表示代码和仓库内测试已有证据；本地指标按样本范围、数据版本和指标配置解释。

## 合规矩阵

| 事项 | 赛题/答疑要求 | 当前证据 | 状态 | 不能声称的内容 | 下一步动作 |
|---|---|---|---|---|---|
| 任务一七字段 | 提取产品/服务名称、品目、品牌（产品供应商）、规格型号、单价、数量、总价；覆盖 HTML 和附件 | `backend/app/parsers.py`、`backend/app/schemas.py`、`docs/ANNOTATION_GUIDE.md`；附件解析和抽取测试 | 已实现 | 不把缺失信息推定成原文抽取值 | 保留字段来源、空值状态和附件 warning，供评审查看 |
| 七字段细粒度 | 赛题允许标的物最细粒度；数量/金额不可从未披露内容臆造 | `docs/ANNOTATION_GUIDE.md`、`docs/QUERY_SEMANTICS.md`；金额政策在 `backend/app/evaluation_policy.py` | 已实现 | 不能把推定值当原文抽取值或计入官方准确率 | 如展示推定，单独标记 `inferred`、保留证据并排除正式字段评测 |
| 品牌与产品供应商 | 题目将品牌称为产品供应商字段；业务术语又指生产厂商或授权经销商 | `backend/app/parsers.py`、`backend/app/model_adapter.py`、`docs/archive/reports/agent1-brand-supplier-report.md`；品牌/供应商回归测试 | 已实现 | 不能把品牌自动映射成法律主体，也不能声称已有独立 `product_supplier` 持久化实体 | 评审演示时分别展示品牌字段和中标供应商；若需法律实体维度，增加来源明确的独立字段 |
| 逻辑推定单价/总价 | QA E8 允许有依据的逻辑计算，并明确推定值不参加精度评估 | 当前抽取与查询保留原文金额，不混入推导金额 | 当前原文值策略已说明 | 不把推定值当原文值，不虚称已实现单独推导功能 | 若增设推导展示，须保存公式、证据并与精度评估隔离 |
| TP/FP/TN/FN | 答疑将有字段记 P、无字段/缺失记 N；赛题公式为 `0.4×Accuracy + 0.3×Precision + 0.3×Recall` | `docs/EVALUATION.md`、`backend/app/evaluation_policy.py`、`backend/app/evaluation.py`、`backend/tests/test_official_qa_metrics.py` | 已实现（可复现的团队解释） | 多值字段、重复记录、实体负样本边界未在答疑中完全形式化 | 报告注明 profile、对齐范围、样本版本和公式，确保本地对比可复核 |
| 任务二场景一 | 指定采购单位，输出合作中标供应商、产品供应商、合作次数和交易总金额；答疑规定产品供应商采用任务一品牌字段 | 新增中标方 `award_project_count`，保留 `award_package_count`；品牌保留项目/包数和明确标的总价；GAP 2.12 合成 oracle、真实 Neo4j/本地回归对照见 `archive/reports/agent-gap-2.12-report.md` | 代码和本地统一回归已通过 | 品牌不是法律实体；标的总价与中标组织的 award 交易额分开，不把未知金额补成成交额 | 展示中标供应商与品牌两组统计、金额来源及未披露值 |
| 任务二场景二 | 指定采购单位，输出 TOP5 参与投标主体及高频协同组合；答疑补充“中与不中都算” | SQLite、Neo4j 查询模板、API 和前端已采用 winner/nonwinner/unknown 默认；新 SQLite oracle 已通过 | 代码和本地统一回归已通过 | `unknown` 表示结果未披露，不能当落标；同项目跨包协同按当前项目口径解释 | `include_winners=false` 仅保留明确 `nonwinner`，查询说明披露口径 |
| 任务二场景三 | 指定中标供应商，输出共同竞标主体及全部参与主体、频次和金额 | `analytics.py`、`graph.py`、`analytics_backend.py` 已同步默认口径；`qa-semantics-20261007-v2.json` 为 SQLite 独立 oracle | 代码和本地统一回归已通过 | SQLite 与 Neo4j 的验证范围按各自报告区分 | 查询返回项目、包、参与方和金额明细，口径见 `docs/QUERY_SEMANTICS.md` |
| 任务二场景四 | 多个中标供应商的共同采购单位、合作频次和合作金额；术语表描述历史项目中的次数 | SQLite/真实 Neo4j、API/受控查询、前端和独立 oracle 同步：每供应商 `award_project_count`、保留包数及唯一中标金额，返回 `project_count_scope` | 代码和本地回归已通过 | 采购单位交集不等于共同项目/同包中标；当前解释按可复现口径呈现 | 设计文档保留每供应商项目计频、包数和唯一 award 金额边界 |
| 任务二场景五 | 多个中标供应商共同参与竞标项目、竞标结果、项目数量和项目总金额 | `analytics.py`、Neo4j Cypher、场景五金额回归测试、`docs/QUERY_SEMANTICS.md` | 已实现并通过本地回归 | 项目级汇总与包级明细分别展示 | 报告项目数、包数、项目金额及金额来源 |
| winner/nonwinner/unknown | 原文术语特指未中标方，答疑补充“中与不中都算”；中标供应商可多个 | 查询默认纳入全部已记录参与主体；`unknown` 显示“结果未披露”；`include_winners=false` 仅包含明确 `nonwinner` | 已实现，边界需披露 | 不能将 `unknown` 推定为落标；资格审查失败等边界未被答疑完整形式化 | 交付文档记录当前可复现口径；若官方另行明确，版本化修改并重算 |
| 资格性/符合性审查失败 | 题目定义审查概念，但没有明确失败主体在场景统计中的计入规则 | 解析器保留主体和 outcome/warning；`docs/QUERY_SEMANTICS.md` 已列为边界 | 需要人工确认 | 不能从“出现审查表”推断已提交投标，也不能把失败自动等同 `nonwinner` | 保留原文证据；对模糊情形使用 `unknown`，在最终报告单列数量 |
| 跨包协同投标 | 题目定义同一或多个项目共同参与；未明确跨包计数单位 | 查询保留项目和包结构；`docs/QUERY_SEMANTICS.md` 说明项目级汇总与包级明细 | 需要人工确认 | 不能声称官方一定按包或按项目计频 | 同时展示项目去重计数、包级证据和参与结果，等待评审口径确认 |
| 附件失效/解析失败 | 数据集含 zip 内 doc/docx/xlsx/pdf/图片；平台需自动解析 | `backend/app/archive_files.py`、附件审计脚本、`docs/DATA_QUALITY.md`、`docs/archive/reports/agent3-attachment-audit-report.md`；失败隔离测试 | 代码已实现但未现场验收 | 19 个程序失败、7 个不支持格式、87 个无效下载不能靠模型恢复；不能声称附件 100% 可读 | 随交付包提供聚合统计和 warning 分类；有源字节且可转换时继续修复 |
| Qwen/DeepSeek 使用 | 使用赛题规定模型系列 | 模型适配器、环境配置、错误保护与网页端点配置 | 已实现配置化接入 | 端点名称不是模型身份或准确性的证明 | 记录实际模型配置与运行范围，密钥不入库 |
| LoRA/QLoRA/微调 | 题面允许符合要求的轻量微调 | 本项目采用 API 推理与工程编排，没有训练或微调产物 | 本版本不采用微调 | 不宣称做过训练或拥有微调权重 | 报告聚焦材料治理、证据校验与任务编排 |
| 资源配置 | QA 建议初赛参照 2 vCPU、4 GB、Ubuntu 24.04 部署条件 | 有界并发设计与 Docker 近似验证报告 | 近似验证已有记录 | 不把 Docker/Windows 测试写成 Ubuntu 实机结果 | 环境、依赖、容量与耗时按实际运行记录披露 |
| Neo4j | 题面“推荐采用 Neo4j”；任务要求关系建模、五场景可视化查询统计展示 | `backend/neo4j_runtime/`、`analytics_backend.py`、`docs/archive/reports/NEO4J_GRAPH_PROJECTION_AUDIT.md`；Docker 集成测试 | 已实现 | `/api/v1/graph` 仍是 SQLite 投影；不能声称所有可视化都由 Neo4j 驱动 | 若评审明确要求图展示也走 Neo4j，再单独迁移投影；当前边界需在文档披露 |
| Vue/Python 栈 | 任务三推荐 Vue 前端、Python 后端 | `frontend/` Vue、`backend/` FastAPI/Python；前端测试和构建、后端测试 | 已实现 | 不能把构建通过当作现场平台验收 | 在源码包标注版本和启动步骤 |
| 查询效率 | 五场景各执行一次，响应为前端发起到结果完全渲染；阈值决赛 <1 秒得满分 | `backend/app/benchmark.py`、`docs/DEVELOPMENT.md`、既有性能快照 | 代码已实现但未现场验收 | Python/SQLite 或本机 HTTP 基准不等同命题方统一平台和浏览器渲染耗时 | 在统一平台记录五场景前端端到端平均响应时间 |
| 过程性文档 | 技术路线对比分析、数据质量分析，Word/PDF | [`deliverables/technical-route-report.md`](../deliverables/technical-route-report.md)、[`deliverables/data-quality-report.md`](../deliverables/data-quality-report.md) | Word/PDF 与 Markdown 源稿已完成 | 格式已生成，指标仍按本地回归范围解释 | 已导出并逐页检查，修改源稿后同步更新正式文件 |
| 系统设计文档 | Word/PDF；业务需求、技术选型、数据模型、功能设计、功能测试效果五模块 | [`deliverables/system-design-report.md`](../deliverables/system-design-report.md)、[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | Word/PDF 与 Markdown 源稿已完成 | 报告覆盖五模块及核心亮点预览 | 已导出并逐页检查，保留工程证据与运行边界 |
| 汇报 PPT | 完整演示 PPT，含核心内容预览 | deliverables/presentation-outline.md | 内容大纲已整理 | 大纲不是 PPT 媒体文件 | 按初赛格式制作并检查展示效果 |
| 汇报视频与系统演示 | 1080p 横屏 MP4；汇报 ≤10 分钟，系统演示 ≤5 分钟 | deliverables/pitch-video-script.md、demo-video-script.md | 两类脚本已整理 | 脚本不是已录制视频 | 按脚本录制并检查画面、声音、时长和完整流程 |
| 源码及配套资料 | 工程文件、版本/环境、注释、官方数据集提取结果、任务二模型、说明文档 | 仓库源码、`README.md`、`docs/DEVELOPMENT.md`、`backend/neo4j_runtime/README.md` | 代码已实现但交付包未验收 | `.data`、密钥、Gold、原始材料不能直接打包；当前未形成最终压缩包 | 从干净检出按白名单打包，附版本、运行和数据说明，排除敏感/大体积运行产物 |

## 关键口径结论

1. **本地数据用途清晰。** reviewed Gold 已参与开发，当前仅作团队开发回归，不作为独立泛化结论。
2. **`official_qa` 是对答疑文本的可复现解释。** 它补齐了可观察字段槽位的 TN，但官方尚未形式化多值字段、重复记录、实体级全体负样本和错值的全部细节。
3. **投标参与方的默认解释采用答疑口径。** 评审答疑明确“中与不中都算”，因此当前默认查询纳入 `winner`、`nonwinner`、`unknown`，并将 `unknown` 显示为“结果未披露”。`include_winners=false` 只统计明确 `nonwinner`，不包含 `unknown`。新口径 `qa-semantics-20261007-v2.json` 已完成 SQLite 与独立 Gold oracle 的 `6471/6471` 校验，未运行 Neo4j；历史双后端同数量结果属于迁移前口径。若评审现场另行说明，应版本化修改并重算查询验证。
4. **Neo4j 是推荐技术，不是题面硬性唯一实现。** 当前五类分析 API 支持 Neo4j 并回退 SQLite；图可视化投影继续读取 SQLite，已在架构和审计文档中披露。
5. **模型端点配置化接入。** 网页配置、连接探测、错误隔离与受控重试构成现有能力；mock、短请求和实际批量运行分别记录，不混称同一种验证。

## 交付前动作清单

- [x] 当前 24 条数据定位为开发回归，历史分数保留 Gold、profile 和输入范围，不再安排独立集。
- [x] 同步任务二 winner/nonwinner/unknown 口径，生成新 SQLite oracle 报告 `qa-semantics-20261007-v2.json`（6471/6471）；本轮统一验收仍需按实际后端记录范围。
- [x] 三份报告已输出 Word/PDF，并完成逐页版式检查；文件见 [`deliverables/`](../deliverables/README.md)。
- [ ] 按 [`deliverables/presentation-outline.md`](../deliverables/presentation-outline.md) 制作 PPT；按 [`deliverables/demo-video-script.md`](../deliverables/demo-video-script.md) 录制汇报/系统演示视频。
- [ ] 从干净检出整理源码及配套资料压缩包，排除 Gold、原始材料、数据库、`.env` 和 `.data` 运行产物。

## 证据使用规则

- 历史 `CHANGELOG.md` 数字只作历史快照；当前数字以对应提交的测试记录为准。
- 本地测试的 “passed” 证明代码行为，不证明官方隐藏数据的准确性。
- 没有证据的字段保持未知，不能为了填满矩阵推断版本、参数规模、附件语义对应关系或官方统计口径。
