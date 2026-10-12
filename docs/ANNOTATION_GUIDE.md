# 人工标注指南（协调员用）

> **这份是给协调员的。** 里面有生成任务包、分配、比较和合并步骤。标注员请看[标注员操作手册](ANNOTATION_ANNOTATOR.md)。

Gold 是本地人工评测数据，不是官方成绩。字段结构见 [Gold JSON Schema](../examples/evaluation_gold.schema.json)，标注口径补充见 [EVALUATION.md](EVALUATION.md)。本指南描述可重复的流程；每一批的样本数、分层覆盖、任务 ID 和文件名都以该批生成的 `sample_summary.json`、`sample_manifest.csv` 与任务包 README 为准。本仓库不保证某个本地 `.data` 任务包仍存在或可分发。

## 生成一批新的任务包

从已完成的后台任务生成分层抽样包。命令在 `backend` 目录执行，输出必须位于该目录的 `.data` 内，并使用一个尚不存在的新目录。以下尖括号内是占位符，运行前换成所选批次的真实任务目录和新输出目录：

```powershell
.\.venv\Scripts\python.exe -m app.annotation_tasks_cli `
  --job-dir ".data\jobs\<completed-job-id>" `
  --output-dir ".data\annotation-tasks\<new-batch-name>" `
  --sample-size <N> --pilot-size <P> --seed <integer>
```

以上参数均为占位符，请替换后再运行。`--sample-size` 是公告样本总数，`--pilot-size` 是两位标注员共同独立标注的校准样本数；pilot 数不能超过样本总数的一半，剩余样本由两人各领一半，因此两者之差必须为偶数。固定整数 seed 可复现抽样。若存在已用于调优或标注的公告，应按需重复添加 `--exclude-notice-id <notice-id>`。CLI 会生成唯一预测、样本清单、覆盖统计、bundle、原件副本及分阶段 ZIP；不要覆盖已有目录。

选 `--job-dir` 时要核对它是目标公告批次的**后台任务目录**，不是数据库目录或查询报告目录。历史快照的来源彼此不同：2026-09-26 是 rules + 本地 RapidOCR 的运行任务，检查点记录 1038/1038 完成；2026-09-27 是另一数据集上的修复后查询快照，报告有 1038 条公告及查询/关系计数。二者不能互换，也不能拼接成同一轮处理。需要复核历史数据时，先根据 [数据接入说明](DATA_INTAKE.md) 与对应的 [9 月 26 日运行摘要](benchmarks/official-full-20260926.json)、[9 月 27 日查询记录](benchmarks/official-full-20260927-analytics.md)确认输入来源和范围；新批次则以实际选择的后台任务为准。运行完成后先检查 `sample_summary.json` 的样本数、分层覆盖、排除数和文件数，再查看 `sample_manifest.csv` 及生成的 `README.txt`，确认分配与来源后才分发。

覆盖类别可以重叠，不是互斥分层；每批可达到的类别覆盖由该批样本和生成摘要决定。正文表格中有候选不表示没有附件。“没有配对 ZIP”也不自动构成有代表性的“仅正文”组；分享结果时引用该批摘要，勿沿用其他批次的类别计数。

## 试标、独立标注与裁决

1. 先把生成的 `pilot-a.ready.zip` 发给 A，把 `pilot-b.ready.zip` 发给 B。两份包含同一 pilot 样本，需独立标注；不要互看答案。实际文件名以该批 `README.txt` 为准。
2. 两人完成任务包所示的全部 pilot 条目后，分别导出 reviewed Gold。协调员运行 [annotation_compare_cli.py](../backend/app/annotation_compare_cli.py) 查看差异，再逐项对照官方原文裁决，形成唯一的 `pilot.adjudicated.json`。比较工具只报告差异，不投票、不选择答案。
3. 口径校准后，分别发送 `annotator-a.ready.zip` 与 `annotator-b.ready.zip`，让两人完成各自互不重叠的正式样本。核对生成摘要和 bundle 确认两份正式任务的公告 ID 不重叠。
4. 协调员把 adjudicated pilot Gold 与两份正式 Gold 合并。不要把两份重复 pilot 原始标注一同并入；Gold 条目数和完整覆盖要求按任务包实际清单确定。

标注员通过共享页面导入分发 ZIP 中的 `*.bundle.json`，必须同时保留 ZIP 内 `sources/` 原件。页面不需要后端 API Key；可使用局域网开发服务上的 `annotation.html`，不要把 `localhost` 地址发给另一台电脑。每条材料应逐包对照原文，解析/OCR 文本只作导航线索。附件缺失、损坏、不可读、来源归属不明或包号有疑问时，不要勾选核验，联系协调员。

页面按 `task_id` 自动保存到当前浏览器的 IndexedDB。更换设备、浏览器配置或交接前，标注员应点“下载进度备份”；恢复时用“载入我的标注任务”载入备份。任务全部核验后导出 reviewed Gold 并交协调员；未完成导出会带 `.partial`，不能用于最终合并。自动保存不能代替下载备份。

## 核对差异和合并

下面以变量展示路径。`$taskDir` 应指向本轮新生成的任务目录；先将试标比较和裁决文件保存到该目录。

```powershell
$taskDir = ".data\annotation-tasks\<new-batch-name>"
.\.venv\Scripts\python.exe -m app.annotation_compare_cli `
  --annotator-a "$taskDir\pilot-a.gold.reviewed.json" `
  --annotator-b "$taskDir\pilot-b.gold.reviewed.json" `
  --output "$taskDir\pilot.comparison.json"
```

协调员对照原文处理差异，手工形成且只保留一份完整 pilot 的 `pilot.adjudicated.json`（`schema_version: "1.0"`、`status: "reviewed"`）。然后按该批生成的任务清单运行合并；只有确实覆盖 canonical predictions 中全部公告时才加 `--require-complete`：

```powershell
.\.venv\Scripts\python.exe -m app.annotation_merge_cli `
  --gold-files "$taskDir\pilot.adjudicated.json" `
               "$taskDir\annotator-a.gold.reviewed.json" `
               "$taskDir\annotator-b.gold.reviewed.json" `
  --predictions "$taskDir\predictions.canonical.json" `
  --output "$taskDir\gold.merged.json" `
  --require-complete
```

如本轮只做部分覆盖，移除 `--require-complete`，并在结果说明中记录抽样范围；不可通过删改公告或真值来绕过校验。合并器拒绝重复公告、draft/空 Gold、输入输出路径相同，以及 Gold 中不存在的公告 ID；完整模式还要求预测中的全部公告都有 Gold。预测与 Gold 包号不同时会报告双方独有包号并继续合并，后续评测按包范围计算漏报/多报。工具不核验答案是否忠于原文，也不替代 pilot 人工裁决。

## 标注口径

证据顺序：明确改写结果的官方更正/补充公告优先；其次是该公告的中标/成交结果正文及明确对应的结果附件。其他同项目材料只有明确记载实际成交结果时才作为补充。招标/采购需求、预算、空白响应模板和常识推断不能当成交事实。同级官方来源互相冲突时记入任务外的协调记录，交协调员核原文裁决。

- **未披露不等于不可读**：原文确实未披露才留空/null。附件缺失、损坏、加密、OCR 不可靠、来源归属不明属于待解决问题，不得当作空值；该公告保持未核验。
- **七字段与金额**：记录产品/服务名称、品目、品牌、规格型号、数量、单价和总价。数量只填数值，不含“台”等单位。金额统一人民币元；不以单价乘数量推导未披露总价，也不把项目总中标额复制到每个标的。不要留下七字段全空的标的行，严格 schema 会拒绝它。
- **包与主体**：按官方包/标段记录；未分包用 `default`。预测只是候选结构，可能漏包或多包；以原文为准，页面可改包号、补加原文包、删除多余预测包。删除已有标注内容的包会弹出确认框；每个包号必须非空且唯一。比较和合并会保留包结构差异并报告，评分器会把不一致计为包级漏报/多报，不要为了让编号匹配预测而改错 Gold。
- **中标方与投标方**：原样记录官方名称，不自行合并简称、分公司或相似主体。中标方要在 `winners` 与 `bidders` 各记录一次，后者结果为 `winner`；只把明确参加投标的主体列入 `bidders`。明确未中标填 `nonwinner`；已确认投标但结果未披露填 `unknown`，不能因为没获奖信息就推定落标。中标金额只填明确披露的该主体/该包金额。
- **联合体**：将公告中的联合体整体名称作为一个投标/中标主体，不拆分成员，也不把同一中标额分配给各成员。Schema 没有联合体成员关系字段；如原文另列成员，记录在外部裁决/审计表。

协调员另存审计表：公告 ID、包号、字段、来源文件及页码/表格行、摘录、处理人与裁决。评测 JSON 是严格结构，不能添加过程备注、出处或争议字段。

当前有专用页面 [annotation.html](../frontend/annotation.html)，无需进入主仪表盘或启动 API。局域网共享页面地址取决于实际开发服务配置和网络；分发 ZIP 前先做一次导入检查。页面按任务 ID 使用 IndexedDB 隔离保存，修改会撤销核验，并可下载进度备份；包号重复、空白标的行、空主体名和非法数字会阻止勾选核验并给出提示。规则卡见 [ANNOTATION_QUICKSTART.txt](ANNOTATION_QUICKSTART.txt)。仍没有来源页码/摘录字段、争议标记或联合体成员结构。不要将任何本地评测结果称为官方准确率；评测指标口径见 [EVALUATION.md](EVALUATION.md)。
