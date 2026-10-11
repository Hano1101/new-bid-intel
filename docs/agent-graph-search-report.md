# SQLite 关系图搜索首版报告

## 实现范围

- `/api/v1/graph` 保留最近项目预览和原有 `nodes`、`links`、`categories`、`project_count`、`total_project_count`、`truncated` 字段。
- `?query=...&type=all|buyer|supplier|project` 在当前 `X-Dataset-ID` 对应的 SQLite 数据库中搜索主体及项目。主体角色根据采购项目、投标记录和中标记录判定；同名项目按稳定的 `project:<id>` 返回，不合并结果。
- 选择结果后以 `entity_type` 和数值 `entity_id` 请求直接相连的 1-hop 关系。`relation_type` 会作为 SQL 条件应用于预览或钻取查询。
- 搜索词通过参数化查询处理，`type`、实体类型、关系类型和 hop 均受枚举/范围约束。SQL 只从固定关系片段中组合，不接受任意 SQL 或 Cypher。
- 当前 schema 没有公告发布时间字段，因此首版不提供时间筛选；`notices.created_at` 是导入记录时间，不用于冒充公告发布时间。

## 上限与筛选口径

- 搜索每页最多返回 20 条；支持稳定排序的 `search_offset` 分页，响应提供 `result_count`、总数 `total_result_count`、`next_offset`、`has_more` 与截断提示。界面可逐页加载，直到结果集完整。
- 图最多返回 100 个节点和 200 条边；请求可将上限调低，不能调高。当前实现的 hop 固定为 1。
- 最近项目预览最多选取 50 个项目。原有 `limit` 参数仍接受 1–200；超过预览上限时按最近项目返回并标记截断。
- 图响应提供实际返回的 `node_count`、`edge_count`、`truncated`、`truncation_hint` 及服务端上限。节点上限可能令实际边数低于边上限。
- 搜索使用 SQLite `instr(lower(...), lower(?))` 做名称/编号子串匹配；主体别名表不作为检索字段。结果按名称、类型和 ID 稳定排序。
- 关系与节点详情均由带条件的 SQLite 查询读取，不将全库节点或边载入 Python 后再筛选。读取路由不调用数据库初始化或模型。

## 索引评估

用合成 schema 执行 `EXPLAIN QUERY PLAN` 后，采购包、投标及中标关系可以利用已有的唯一索引/主体索引；项目买方反查和采购标的按包查询原先会扫描关系表。为这两条实际访问路径增加了 `projects(buyer_organization_id)` 与 `procurement_items(package_id)` 索引。名称采用包含匹配，普通 B-tree 前缀索引不能有效加速该条件，因此没有额外增加名称索引。

## 验证结果

- 合成 SQLite/API 测试：`pytest -q tests/test_graph_search_api.py tests/test_graph.py tests/test_datasets.py`，30 passed、2 skipped；新增分页连续性和非法 offset 回归。
- Ruff：`python -m ruff check .`，通过。
- 前端测试：`npm test`，67 passed；新增“加载更多”分页交互回归。
- 生产构建：`npm run build`，通过。Vite 提示现有主 bundle 超过 500 kB；不影响构建结果。
- 测试仅使用临时合成 SQLite 数据。没有对官方全量数据运行模型，也没有向官方数据集写入记录。

## 手工验收步骤

1. 在应用中切换到目标数据集，打开“主体关系图”；确认最近项目预览、刷新和原有缩放/拖动行为可用。
2. 输入一个只存在于较早项目中的采购单位或供应商，选择对应类型并搜索；确认能从全数据集找到候选，不受当前预览节点限制。
3. 搜索一个重名项目或主体，确认候选显示类型和稳定 ID；选择其中一条，确认图只显示该实体的直接 1-hop 关系。
4. 切换“关系筛选”，确认服务器返回的关系类型随之变化；选择“返回最近项目预览”确认回到预览视图。
5. 搜索不存在的名称，确认显示空结果；用高连接度主体检查节点/边计数和截断提示。
6. 搜索命中超过 20 条的宽泛名称，确认“加载更多结果”可继续取回后续候选且不重复；切换数据集后再次搜索同一名称，确认结果仅来自当前 `X-Dataset-ID` 指定的数据集。
