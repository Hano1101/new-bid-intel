# 发布与提交检查清单

本清单用于源码压缩包、评审演示和最终比赛材料准备。它不替代主办方最新通知；正式提交前按学校初赛的格式和截止时间核对。

## 代码与环境

- [ ] `git status` 中没有 `.env`、API Key、密码、`.data`、原始官方文件、`node_modules`、虚拟环境或构建缓存。
- [ ] `README.md`、`docs/DEVELOPMENT.md` 和 `docs/REVIEWER_GUIDE.md` 的启动命令一致。
- [ ] 记录 Python、Node、Docker、Neo4j、LibreOffice 和 OCR 版本。
- [ ] `backend/.env.example` 与 `frontend/.env.example` 只包含变量名和安全示例值。
- [ ] `git diff --check` 通过。

## 自动化验证

- [ ] 后端 pytest 通过，Ruff 通过。
- [ ] 前端 `npm test` 和 `npm run build` 通过。
- [ ] 至少完成一次离线启动、导入、五类查询、标注页和退出流程。
- [ ] 若提交 Neo4j 能力，完成 Docker 集成测试，并记录 SQLite 对照结果。
- [ ] 换机或更换网络后，按 [`LAN_ACCEPTANCE.md`](LAN_ACCEPTANCE.md) 复查演示地址与登录。

## 数据与评测

- [ ] 明确区分原始材料、团队 reviewed 开发回归数据和预测结果。
- [ ] 不把 `predictions.canonical.json` 当真值；不把 24 条 tuning 指标或全量产出写成官方准确率。
- [ ] 引用结果绑定代码、提示词、Gold/输入版本和指标 profile。
- [ ] 本地回归报告说明完成范围、字段/记录/实体指标、包号集合对齐、耗时与缓存条件；不使用 final 标签暗示独立性。
- [ ] 报告写明样本、指标 profile 和团队本地回归口径。

## 比赛要求映射

源码包应包含或链接到：

- [ ] 任务一七字段和主体抽取说明、来源证据和可导出的结果数据表。
- [ ] 任务二数据模型、五类查询口径、SQLite/Neo4j 选择和金额汇总定义。
- [ ] 任务三功能说明、运行步骤、评审账号交付方式和离线兜底。
- [ ] 依赖、版本、关键代码注释、测试结果和已知限制。
- [x] 系统设计、技术路线和数据质量三份 Word/PDF 已生成并逐页检查，见 [`deliverables/README.md`](../deliverables/README.md)。更改报告后重新检查。
- [ ] 按 [`deliverables/presentation-outline.md`](../deliverables/presentation-outline.md) 制作 PPT，按 [`deliverables/demo-video-script.md`](../deliverables/demo-video-script.md) 录制并检查视频。

## 发布后核对

- [ ] 评审机重新创建干净数据集，确认不会混入开发数据。
- [ ] 模型服务不可用时，离线 rules 路径仍能展示导入、关系查询和人工核验。
- [ ] Neo4j 不可用时，API 显示 SQLite 回退而不是静默声称使用图数据库。
- [ ] 所有对外截图和文档去除姓名、学校、内网地址、API Key、密码和本机绝对路径。

仓库当前没有声明开源许可证。若需要公开发布源码，请先由项目负责人选择并添加明确的 `LICENSE` 文件；在此之前不要在 README 中暗示“可自由再分发”。
