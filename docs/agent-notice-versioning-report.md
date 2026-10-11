# 公告和附件版本变更追踪实现报告

2026-10-11；独立 worktree：`D:\ICT\bid-intel-notice-versioning`，基线 `36f8bf6`。本轮没有 commit、push 或合并回主工作区。

## 实现与边界

实现独立的版本存储、差异计算、只读路由、本地结构化快照导入路由、版本历史和差异 Vue 组件。`main.py` 只有两个 router 的 import/注册；`App.vue` 只接组件和冻结证据入口。存储保存动作和既有导入流程做最小接线。

没有改模型 prompt、解析规则、包号识别、Gold、三路线评测器或查询/评测口径，没有调用真实模型 API，也没有读取或改写官方评测产物。测试只使用构造材料、mock、本地临时数据库及既有单元测试 fixture；不据此声称发现了真实历史公告变更。

## 数据模型与迁移

每个数据集继续使用独立 SQLite 文件，并在版本表中显式保存 `dataset_id`。默认库对应 `default`，`datasets/<32位ID>.sqlite` 对应该数据集 ID。HTTP 路由复用既有 `DatabasePath`，不接受客户端数据库路径。

| 表 | 内容 |
| --- | --- |
| `notice_version_groups` | 随机版本组 ID、数据集 ID、初始身份资料/状态、创建时间 |
| `notice_version_identities` | 来源命名空间下的官方公告/来源唯一标识 token，或项目编号与采购单位组合 token；可记录后续确认的强身份 |
| `notice_versions` | 随机版本 ID、组/数据集/公告 ID、UTC 导入时间、原因、该次身份状态/资料、去重指纹、完整结构化快照 |
| `notice_version_links` | 数据集内公告记录到冻结版本的引用 |

结构化快照包含元数据及字段证据/状态、正文纯文本、来源文件清单、采购包、投标主体、中标记录、标的字段及证据/定位。每份来源保存文件名、原始 SHA-256、字节大小和导入时间；能够计算时另存 HTML 规范化结构指纹。不会保存上传原始字节、PDF/附件副本或 HTML 原件。没有保存过的正文或哈希明确为不可用，不猜测补齐。

建表和索引采用幂等迁移，不重建或清空现有核心表。版本表的 UPDATE/DELETE 有 SQLite 触发器拒绝；版本不依赖对可变公告表的级联外键。旧数据库迁移仅增加空版本表，不从当前记录推断历史导入时间、旧正文或旧版本。若既有替换回执指向没有冻结快照的旧公告，替换会明确拒绝，要求独立导入以保留旧记录。

## 身份、保存与去重

身份优先使用明确提供的 `official_notice_id` / `source_unique_id`，并以 `namespace` 隔离不同来源。既有元数据不含官方公告 ID，普通上传不会从文件名或项目名编造这类身份；可通过独立结构化导入显式提供。没有强身份时，只接受非占位的项目编号与采购单位组合，项目名称不是关联键。只有项目编号、只有标题、缺采购单位或编号为“未知/未公示/N/A”等时不能自动关联。

多个强标识分别命中不同组、已有强身份相互矛盾时，独立保存为 `identity_ambiguous`；缺可靠身份时独立保存为 `manual_link_required`，前端显示“身份待确认”。不提供任意组 ID 强行并组的参数。第一份可靠快照为 `matched`，同组变化为 `new_version`，等价重复为 `duplicate_snapshot`。去重不把待确认状态改成已确认。

快照指纹保留来源文件哈希/大小以及业务和证据字段，忽略数据库自增 ID、导入时间、模型置信度、方法名与诊断 warning；JSON 键顺序和等价数值不影响指纹。行集合按多重集合处理，不丢重复采购行。同一组完全相同快照复用既有版本；身份冲突的同一份重复材料也可去重，但仍保持待确认。原始文件字节不同的 HTML 格式变化会保留新的文件指纹版本，比较时显示“仅格式变化”。重复旧快照不会把最新版本回退到旧版。

核心入库与版本捕获在同一 `BEGIN IMMEDIATE` 事务内完成，捕获失败整次回滚；并发重复导入不会创建重复版本。普通变化导入保留旧公告行；既有批量重试的可变投影替换行为和人工复核候选代次保持兼容，其旧版本/证据独立保留。公告 ID 分配参考冻结历史，避免删除投影后将旧公告 ID 分配给无关公告。证据链接使用版本 ID 加公告/候选 ID，兼容候选行 ID 在重试时复用。

## 差异分类

每条差异返回 `entity_type`、`entity_key`、`field`、`change_type`、`before`、`after`、`before_source`、`after_source`、`requires_manual_confirmation` 和 `classification`。摘要按实体、变化类型以及分类计数。

覆盖公告名称/编号/单位/预算/成交额、正文、文件清单/hash/大小、包号/包名/金额、主体/结果/联合体、中标主体/金额，以及标的名称/品目/品牌/型号/数量/单价/总价；已有字段证据、空值状态、来源文件与定位变化也保留。默认省略完全未变字段，`include_unchanged=true` 可返回它们。

| 分类 | 规则 |
| --- | --- |
| `possible_semantic` | 明确业务值增删改，或附件字节改变但无法证实只是格式变动 |
| `format_only` | 空白/换行或数字表示等价；HTML DOM 规范指纹相等而原 SHA-256/大小不同 |
| `provenance_only` | 来源定位、片段或字段状态变化；不把它直接等同于采购事实改变 |
| `unchanged` | 值和已保存表示未变，仅在显式要求时返回 |

HTML 比较忽略空白节点/属性顺序；JSON 对象忽略字段顺序；金额/数量使用精确 Decimal 等价，包号和型号等标识不会数值化，`01` 不会自动等同于 `1`。不能通过通用字符串去空白把 `1 0` 合成 `10`。

包号、主体名、标的身份字段发生变化时，只有唯一来源定位/名称等候选对应才会暂配对，并标“待人工确认”；重复或冲突行不会按列表顺序强行配对。新增/删除仍保留整行和对应证据。没有附件原始字节和独立语义解析证明时，哈希变化只代表可能变化，需要人工确认。

## API 与界面

只读接口均在 `/api/v1/notice-versions` 下，复用 `X-Dataset-ID` 和现有登录保护：

| 方法与路径 | 功能 |
| --- | --- |
| `GET /notices/{notice_id}` | 版本列表、最新版本 ID、身份状态；未追踪记录返回明确空列表 |
| `GET /notices/{notice_id}/latest` | 最新完整快照；无版本返回 404 |
| `GET /versions/{version_id}` | 指定冻结快照 |
| `GET /versions/{version_id}/evidence` | 兼容既有证据弹层的冻结详情，包含正确旧版候选和已保存哈希 |
| `GET /compare?before_version_id=...&after_version_id=...` | 逐条差异和摘要，可选 `include_unchanged` |
| `GET /summary?before_version_id=...&after_version_id=...` | 仅摘要 |

版本 ID 限定为 32 位小写十六进制；跨数据集版本不可访问，跨版本组比较返回 409。只读 router 没有 POST/PUT/PATCH/DELETE、SQL 或服务器文件访问入口。

独立的 `POST /api/v1/notice-version-imports` 只接收结构化 `ImportResult`、来源指纹、可选身份/纯文本正文/显式采购包和原因。无需再次抽取或模型调用；字段白名单拒绝数据库路径、SQL、原文件字节和任意手工组 ID。它是有意设计的新增导入入口，不属于只读 router。显式包结构只写版本快照，不改变原有包号抽取与分析投影。提供的文件指纹是调用方声明，本接口未持有原文件，不能独立验明原件。

普通公告上传、上传批量导入和后台保存都会在现有 `save_import` 入口捕获版本。普通上传是否使用模型仍遵守原配置，本轮测试没有启用真实模型；已经有结构化结果时应使用上述独立入口避免再次抽取。

打开既有“公告详情与原文证据”弹层，底部可看版本历史，查看当前或旧版元数据及文件指纹，选择两版比较。差异可以按公告字段、正文、附件/来源文件、采购包、投标主体、中标记录、标的，以及增/删/改、格式/语义/来源和待确认状态筛选。证据按钮加载冻结版本详情，不用可变候选 ID 猜测旧原文。数据集切换和旧请求返回不会覆盖新视图。

### API 示例

以下 ID 均为示例占位，实际使用导入响应的 `notice_id`、`version_id`；所有调用均在同一数据集内。

```powershell
curl.exe -H "X-Dataset-ID: default" http://127.0.0.1:8000/api/v1/notice-versions/notices/1
curl.exe -H "X-Dataset-ID: default" http://127.0.0.1:8000/api/v1/notice-versions/notices/1/latest
curl.exe -H "X-Dataset-ID: default" "http://127.0.0.1:8000/api/v1/notice-versions/compare?before_version_id=<OLD_ID>&after_version_id=<NEW_ID>"
curl.exe -H "X-Dataset-ID: default" "http://127.0.0.1:8000/api/v1/notice-versions/versions/<OLD_ID>/evidence"
curl.exe -X POST -H "Content-Type: application/json" -H "X-Dataset-ID: default" --data-binary "@snapshot.json" http://127.0.0.1:8000/api/v1/notice-version-imports
```

`snapshot.json` 的最小结构示例（SHA-256 应替换为真实来源指纹）：

```json
{
  "snapshot": {
    "notice_id": 0,
    "source_files": ["notice.html"],
    "items_found": 0,
    "items": [],
    "participants": [],
    "metadata": {"project_name": "合成设备采购", "project_number": "SYNTH-001", "procurement_unit": "合成采购中心"}
  },
  "identity": {"official_notice_id": "SYNTH-NOTICE-1", "namespace": "synthetic-example"},
  "sources": [{"source_file": "notice.html", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "byte_size": 123}],
  "body_texts": {"notice.html": "合成公告正文"},
  "reason": "采购人员导入结构化更正快照"
}
```

保持同一可靠身份，再导入更正字段和新的来源指纹，会返回新的版本 ID；重复内容返回 `duplicate_snapshot`。返回的状态用于判断是否待人工确认，不能把 `matched` 当成字段已验证或材料真实性证明。

## 验证

工作目录分别为独立 worktree 的 `backend` 和 `frontend`。后端使用主工作区现有 Python 环境执行，但 `PYTHONPATH` 明确指向独立 worktree；不读取主库和个人模型配置。

```powershell
# D:\ICT\bid-intel-notice-versioning\backend
$env:PYTHONPATH=(Get-Location).Path
& D:/ICT/bid-intel/backend/.venv/Scripts/python.exe -m pytest tests/test_notice_version_api.py tests/test_notice_version_storage.py tests/test_notice_version_diff.py -q
& D:/ICT/bid-intel/backend/.venv/Scripts/python.exe -m pytest -q
& D:/ICT/bid-intel/backend/.venv/Scripts/python.exe -m ruff check app tests

# D:\ICT\bid-intel-notice-versioning\frontend
npm test
npm run build

# D:\ICT\bid-intel-notice-versioning
git diff --check
```

版本专项已通过 **88 passed、1 warning**（10.51 秒），覆盖全部请求的存储/身份/迁移/并发/不可覆盖、业务字段/来源差异、隔离/受控 API 和冻结证据行为；另含身份冲突材料重复去重回归。最终后端全量 `pytest -q -ra` 为 **662 passed、7 skipped、2 warnings**（196.27 秒）；7 项跳过分别为 3 项真实 Neo4j 集成、1 项 LibreOffice DOC 转换和 3 项缺 Windows 符号链接权限的测试。前端全量 **80 passed**（约 0.77 秒），包括新增 13 项组件/工具回归；生产构建通过（6.56 秒），保留既有大 chunk 提示。Ruff `app tests` 和 `git diff --check` 通过。

此前曾发现批量替换与人工复核 ID 兼容性问题，已修复并通过相关定向回归，不将首次失败运行当作通过证据。后端 warning 为 FastAPI/TestClient 依赖弃用和既有 ZIP 重名 fixture 提示。

## 未完成的部署、验收与限制

- 未合并主 worktree、未部署、未进行真实同一公告多版本业务验收、第二台设备或浏览器视口人工验收。本次合成版本只证明实现行为。
- 待确认身份可保存和展示，尚无人工关联/拆组操作界面或审计流程。编号或采购单位变化但没有稳定强身份时，不自动认定为同一公告。
- 不自动制造历史版本；升级前已被覆盖的内容无法恢复。后台缓存保存若没有正文纯文本，只能比较已保存的候选、证据和指纹，API 用 `body_status=not_saved` 明确说明正文未保存。
- 不存原始字节，不能下载旧附件或证明其真实内容变化；快照证据不是原件归档。HTML 格式规范化也不是附件二进制格式识别器。
- 版本追踪不重写现有五类分析口径，分析仍读取原核心表，不自动改成“只统计版本组最新公告”；普通新快照的独立公告投影可能继续作为独立项目参与原分析。这项业务选择需要主 Agent 与采购人员验收后决定。
- 独立结构化导入 API 尚无独立上传 UI；既有文件导入 UI 自动记录版本。结构化包名/包金额需显式提供，版本功能不会补强包号抽取规则。
- 版本列表和大正文差异暂未分页或分词高亮；真实大库规模、并发容量与备份/保留策略仍需部署验收。
- 前端生产构建保留既有大 chunk 提示；后端部分环境集成/可选转换测试按其原条件跳过，不代表真实 Neo4j/外部工具验收完成。

不需要主 Agent 再接线 `App.vue` 或 `main.py`；仍需要审查本 worktree 的最小接线及新增文件，并在其统一集成流程中合并和部署。

## 修改和新增文件清单

以下路径均相对独立 worktree `D:\ICT\bid-intel-notice-versioning`，共修改 6 个、新增 13 个文件。

| 操作 | 文件 |
| --- | --- |
| 修改 | `backend/app/storage.py` |
| 修改 | `backend/app/ingestion.py` |
| 修改 | `backend/app/schemas.py` |
| 修改 | `backend/app/main.py` |
| 修改 | `frontend/src/App.vue` |
| 修改 | `frontend/src/components/NoticeEvidenceDialog.vue` |
| 新增 | `backend/app/notice_versions.py` |
| 新增 | `backend/app/notice_version_diff.py` |
| 新增 | `backend/app/version_api.py` |
| 新增 | `backend/app/version_import_api.py` |
| 新增 | `backend/tests/test_notice_version_storage.py` |
| 新增 | `backend/tests/test_notice_version_diff.py` |
| 新增 | `backend/tests/test_notice_version_api.py` |
| 新增 | `frontend/src/components/NoticeVersionHistory.vue` |
| 新增 | `frontend/src/components/NoticeVersionDiff.vue` |
| 新增 | `frontend/src/utils/versionDiff.js` |
| 新增 | `frontend/tests/notice-version-component.test.js` |
| 新增 | `frontend/tests/notice-version-utils.test.js` |
| 新增 | `docs/agent-notice-versioning-report.md` |
