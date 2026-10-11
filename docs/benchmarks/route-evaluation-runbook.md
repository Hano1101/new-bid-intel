# 三路线评测准备

评测分两层：`app.gold_route_evaluation` 回放 `rules`、`hybrid`、`model` 并保存预测、字段/记录/实体指标、请求/耗时/token 遥测；`app.route_evaluation_report` 只读这些产物，补充包号集合对齐、重复候选和附件/OCR覆盖，并生成可粘贴到 GAP 的 Markdown 表。

所有本地报告必须写明“团队本地验证，不是官方成绩”。`gold.merged.json` 是已使用过的 reviewed 回归数据；它用于工程回归和诊断，不作为官方评分替代。现有 24 条 reviewed 数据已经参与调试，本手册只安排开发回归。

从 `backend` 目录执行。冻结抽取代码、提示词、模型参数后，先对受影响公告使用全新的输出目录做定向复评：

```powershell
$py = ".venv/Scripts/python.exe"
$gold = ".data/annotation-tasks/official-20260926-LHH-YHR/gold.merged.json"
$manifest = ".data/annotation-tasks/official-20260926-LHH-YHR/sample_manifest.csv"
$sourceRoot = "<本机已授权原始材料目录>"
$run = ".data/annotation-tasks/official-20260926-LHH-YHR/evaluation-agent1-targeted"

& $py -m app.gold_route_evaluation `
  --gold $gold --manifest $manifest --source-root $sourceRoot `
  --output-dir $run --scope attachments `
  --notice-id <受影响公告ID> --notice-id <另一个受影响公告ID>

& $py -m app.route_evaluation_report `
  --gold $gold --manifest $manifest --run-dir $run `
  --dataset-role targeted --stage targeted --metric-profile official_qa
```

定向报告用于确认改动影响，推荐状态会保持 pending，不得当作最终路线结论。

对现有 24 条开发回归材料运行三路线时，使用新输出目录并保留旧报告：

```powershell
$regressionGold = ".data/annotation-tasks/official-holdout-20260929/gold.reviewed.json"
$regressionManifest = ".data/annotation-tasks/official-holdout-20260929/sample_manifest.csv"
$run = ".data/annotation-tasks/official-holdout-20260929/evaluation-routes-regression-new"

& $py -m app.gold_route_evaluation `
  --gold $regressionGold --manifest $regressionManifest --source-root $sourceRoot `
  --output-dir $run --scope attachments

& $py -m app.route_evaluation_report `
  --gold $regressionGold --manifest $regressionManifest --run-dir $run `
  --dataset-role tuning --stage targeted `
  --metric-profile official_qa
```

`--stage final` 是工具保留的独立性闸门，现有开发回归集合不使用它，也不因旧目录名含 holdout 而成为独立集。报告的路线推荐使用透明的团队本地规则：最大化 `min(field_micro.weighted_score, records.weighted_score)`，再比较两者均值、包号集合精确对齐率，平局时选择重复候选更少、请求更少的路线。这只是团队辅助决策规则，不替代官方评分公式。

答疑之后的报告显式选 `official_qa`，它是团队对 TP/FP/TN/FN 的解释，不是官方评分器。runner 仍保留历史 `local_proxy` 报告；报告后处理从预测重新计分，保留金额容差等配置和原抽取哈希，另记录 `metric_code_sha256`，不调用模型。

已有运行不要直接作废或覆盖：先检查三路线是否全部完成、来源/Gold/模型配置和抽取代码哈希。只改查询或前端无需重做模型抽取；只改评分可用既有完整预测在新报告路径重算。抽取或提示词发生变化时，检查 runner 的兼容性校验，保留旧响应和预测后再决定需重跑的范围，不能手改旧运行哈希冒充冻结版本。
