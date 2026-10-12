# 三路线本地开发回归

本手册说明如何对已核验样本运行 `rules`、`hybrid`、`model` 并生成只读报告。模型路线会调用当前配置的服务并产生费用；先确认端点、样本授权、输出目录和预算。不要覆盖既有运行目录或原始 Gold、预测和材料。

团队现有 24 条 reviewed 数据已经参与开发调试，只可作为本地 tuning 回归材料。旧目录即使含有 `holdout` 字样，也不会令这组数据成为独立测试集；报告应使用 `dataset-role tuning` 和 `stage targeted`，不得把它表述为 final、独立泛化结果或官方成绩。不同日期、附件范围或 metric profile 的历史结果应分别引用，不能合并成统一基线。

从 `backend` 目录运行。先按当前授权文件替换以下 Gold、清单和源材料路径，并为每次新运行指定空输出目录：

```powershell
$py = ".venv/Scripts/python.exe"
$gold = ".data/evaluation/reviewed-gold.json"
$manifest = ".data/evaluation/sample-manifest.csv"
$sourceRoot = "<本机获准原始材料目录>"
$run = ".data/evaluation/runs/dev-regression-new"

& $py -m app.gold_route_evaluation `
  --gold $gold --manifest $manifest --source-root $sourceRoot `
  --output-dir $run --scope attachments --pilot-only --concurrency 1

& $py -m app.route_evaluation_report `
  --gold $gold --manifest $manifest --run-dir $run `
  --dataset-role tuning --stage targeted --metric-profile official_qa
```

只验证改动关联的公告时，为 `gold_route_evaluation` 增加一个或多个 `--notice-id <ID>`，并将范围标为 `targeted`。定向结果用于诊断受影响样本，不能据此排列路线总表现。

报告生成器对已有预测只读重算指标，不发出模型请求，也不改写 Gold、预测或原始材料。需切换 `official_qa` 或 `local_proxy` 时显式填写 `--metric-profile`；这两种 profile 是团队约定，`official_qa` 不是主办方评分器。指标定义见 [`EVALUATION.md`](../EVALUATION.md)。

若要续跑同一输出目录，必须保持 Gold、源材料、模型配置、抽取选项和代码身份不变；runner 会校验冻结身份，跳过已完成样本并将中断项记为新尝试。失败样本只有带 `--retry-failed` 才会再次运行。先查看 `progress.json` 和供应商用量；断线后重试不能保证供应商未处理或未计费。历史数据与运行范围见仓库 [归档索引](../../archive/README.md)。
