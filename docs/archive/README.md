# 历史文档归档

本目录保存已完成任务的专项报告、历史审计和原始补丁，用于复查工程依据。2026-10-11 从 `docs/` 顶层移入 25 份报告及 1 份配套补丁；正文中的日期、测试数字和验收状态保留当时含义。当前功能、运行步骤和任务状态以[项目文档索引](../DOCUMENTATION_INDEX.md)中的现行文档为准。

## 抽取和数据质量

- [品牌与供应商修复](reports/agent1-brand-supplier-report.md)
- [附件用途过滤](reports/agent-attachment-scope-report.md)
- [PDF 页码与用途验证](reports/agent-gap120-pdf-validation-report.md)及[原始最小补丁](reports/agent-gap120-pdf-page-markers.patch)
- [跨文件候选融合](reports/agent-candidate-reconciliation-report.md)
- [附件审计](reports/agent3-attachment-audit-report.md)
- [官方数据接入与全量处理记录](reports/OFFICIAL_INTAKE_REVIEW.md)
- [原文证据链](reports/agent-evidence-chain-report.md)

## 评测与查询口径

- [金额评测政策实现](reports/agent2-evaluation-policy-report.md)
- [评测与 Gold 审计](reports/agent-evaluation-semantics-audit.md)
- [Gold 来源复核](reports/agent-gold-source-verification.md)
- [cache-only 回放](reports/agent-gap-priority1-cache-only-replay-report.md)
- [查询答疑审查](reports/agent-qa-query-semantics.md)
- [查询语义迁移](reports/agent-query-semantics-migration-report.md)
- [前端查询验收](reports/agent2-frontend-query-acceptance.md)
- [合作项目计数修复](reports/agent-gap-2.12-report.md)
- [Neo4j 图投影审计](reports/NEO4J_GRAPH_PROJECTION_AUDIT.md)

## 界面和业务流程

- [服务器材料目录选择器](reports/agent-batch-directory-picker-report.md)
- [关系图搜索](reports/agent-graph-search-report.md)
- [线索折叠与公告弹层](reports/agent-clue-modal-ux-report.md)
- [人工复核队列](reports/agent3-review-queue-report.md)
- [公告版本追踪](reports/agent-notice-versioning-report.md)

## 并发与工程整合

- [有界并发交付概述](reports/bounded-delivery.md)
- [有界并发验证记录](reports/bounded-validation.md)
- [资源限制验证](reports/agent3-resource-limited-validation.md)
- [2026-10-07 统一整合审查](reports/CONSOLIDATION_REVIEW_2026-10-07.md)

当前并发配置和操作命令见[后台任务手册](../bounded-jobs.md)及[评测器手册](../bounded-route-evaluation.md)。带时间和数据范围的机器报告继续保存在 [`benchmarks/`](../benchmarks/)。

重复的 `EVALUATION_QA_POLICY.md` 已合并到[评测说明](../EVALUATION.md)的 `official_qa` 小节，今后只维护该处口径。
