# 项目文档总索引

本文是源码、运行说明和比赛交付源稿的统一入口。项目包含可运行的采购公告智能抽取、关系分析、证据复核和版本追踪流程；按下列路线可从首次启动进入功能演示。

## 按目标阅读

| 目标 | 文档 |
|---|---|
| 快速了解作品并启动演示 | [`JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md) |
| 登录、浏览与实际操作演示 | [`REVIEWER_GUIDE.md`](REVIEWER_GUIDE.md) |
| 产品功能、架构与数据流 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| 安装依赖、启动、测试和开发 | [`DEVELOPMENT.md`](DEVELOPMENT.md) |
| 模型抽取、规则路线和证据校验 | [`MODEL_AND_EXTRACTION.md`](MODEL_AND_EXTRACTION.md) |
| 数据来源、附件解析与质量处理 | [`DATA_QUALITY.md`](DATA_QUALITY.md) |
| 五类查询、筛选和金额口径 | [`QUERY_SEMANTICS.md`](QUERY_SEMANTICS.md) |
| 本地评测工具和指标定义 | [`EVALUATION.md`](EVALUATION.md) |
| LAN 部署参数和网络排查 | [`LAN_ACCEPTANCE.md`](LAN_ACCEPTANCE.md) |
| 工程开发进度与技术边界 | [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) |
| 版本变化记录 | [`CHANGELOG.md`](CHANGELOG.md) |

## 专项操作手册

| 目标 | 文档 |
|---|---|
| 新队友交接与开发约束 | [接手说明](ONBOARDING.md) |
| 导入附件、选择服务器目录与批量处理 | [数据接入](DATA_INTAKE.md) |
| 配置任务并发、暂停续跑和资源额度 | [后台任务运行说明](bounded-jobs.md) |
| 运行三路线开发回归 | [评测器说明](bounded-route-evaluation.md)、[操作步骤](benchmarks/route-evaluation-runbook.md) |
| 组织标注与实际填写 | [标注协调手册](ANNOTATION_GUIDE.md)、[标注员操作说明](ANNOTATION_ANNOTATOR.md) |
| 配置和验证模型端点 | [模型端点操作说明](MODEL_ENDPOINT_ACCEPTANCE.md) |
| 功能规划与赛题要求对应 | [创新路线图](INNOVATION_ROADMAP.md)、[QA 对照矩阵](QA_COMPLIANCE_MATRIX.md) |
| 发布和打包 | [发布检查](RELEASE_CHECKLIST.md) |
| 查找已完成任务的历史证据 | [归档索引](archive/README.md) |

`docs/` 顶层保留当前使用与维护的文档；`archive/reports/` 集中保存阶段性 Agent 报告和历史审计；`benchmarks/` 保留带运行范围的评测数据与运行手册。比赛报告、PPT 大纲及视频脚本统一放在 `deliverables/`。

## 评委演示路线

建议先按 [`JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md) 启动离线演示，再按 [`REVIEWER_GUIDE.md`](REVIEWER_GUIDE.md) 依次查看公告证据、五类分析、关系线索、人工复核和公告版本比较。离线演示数据明确标记为虚构；需要展示业务材料时，可通过导入流程使用已准备的公告和附件。

## 验证基线

在提交 `c1fc4c4` 对应的代码快照上，记录的工程验证为：后端 `662 passed, 7 skipped, 2 warnings`，Ruff 通过，前端 `80 passed` 且生产构建成功。跳过项依赖 Neo4j、LibreOffice 或 Windows 符号链接等环境条件。执行新验证时以当次命令输出为准。

团队使用的 24 条 reviewed 数据参与过开发调试和回归；它们属于本地开发回归材料，不能代表官方评分结果或独立泛化评估。工程测试和本地回归用于验证功能行为，不代替赛事评分。

## 比赛交付源稿

[`deliverables/README.md`](../deliverables/README.md) 汇总了当前可维护的 Markdown 源稿、正式报告格式说明、PPT/视频材料和源码资料包规则。系统设计、技术路线、数据质量三份报告已提供 Word/PDF 阅读版，并保留以下可维护源稿：

- [`system-design-report.md`](../deliverables/system-design-report.md)：系统设计说明。
- [`technical-route-report.md`](../deliverables/technical-route-report.md)：技术路线与本地实验范围。
- [`data-quality-report.md`](../deliverables/data-quality-report.md)：数据接入、附件质量和证据处理。
- [`presentation-outline.md`](../deliverables/presentation-outline.md)：答辩演示内容结构。
- [`pitch-video-script.md`](../deliverables/pitch-video-script.md) 与 [`demo-video-script.md`](../deliverables/demo-video-script.md)：项目汇报和系统演示讲稿。
- [`source-data-index.md`](../deliverables/source-data-index.md)：源码及配套资料的整理规则。

## 阅读和公开规则

`GAP_ANALYSIS.md` 跟踪当前任务与技术边界，`CHANGELOG.md` 和[归档报告](archive/README.md)保留工程决策与历史验证。归档报告中的“未合并”“待验收”和测试数字均属于当时快照，不自动代表当前状态。公开文档和交付包不得包含 `.env`、API Key、数据库、`backend/.data`、评审账号或未经审查的原始材料；引用数据应提供范围和统计口径。
