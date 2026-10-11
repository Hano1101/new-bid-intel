# 关系线索折叠与公告详情弹层修复报告

> 历史报告，已于 2026-10-11 归档。正文保留当时的结论和验证范围；当前实现请查阅[项目文档索引](../../DOCUMENTATION_INDEX.md)。

## 修改内容

- 关系线索卡片默认收起摘要、主体、公告/项目/包明细、公告证据入口和数据质量提示；标题、线索类型、待核查状态及已有项目/包指标保持可见。每张卡和“全部展开/全部收起”均使用原生按钮，并同步 `aria-expanded` 与 `aria-controls`。统计口径说明继续常驻展示。
- 公告详情与证据片段分别通过 Vue `Teleport` 挂到 `body`，避开 `.page-stage` 的 `will-change: transform` 定位上下文。打开时固定背景页面并保留原滚动坐标，弹层内容独立滚动；关闭时还原原有 body 样式、滚动位置和打开前的焦点。关闭按钮、遮罩、Escape 和片段二级弹层仍可用。
- 新增 `frontend/tests/relationship-clues.test.js`，覆盖默认折叠、单卡展开/收起、全部展开/收起、计数与明细保留，以及公告证据入口事件。

## 验证

- `node --test tests/relationship-clues.test.js`：4 项通过。
- 除 `batch-jobs.test.js` 外运行其余前端测试：46 项通过。
- `npm run build`：通过。
- 全量 `npm test` 中，`batch-jobs.test.js` 的两项目录浏览测试失败，并出现 Vue “Unhandled error during execution of directive hook” 警告。该测试文件及 `BatchJobs.vue` 属于工作区原有的其他改动，本次没有修改。
- 仓库没有 Playwright、Puppeteer、Cypress 等浏览器级测试配置或依赖。现有 `tests/browser.test.js` 只验证浏览器工具函数，因此这里没有用 JSDOM 推断弹层几何。

## 手工视口验收步骤

1. 在 `D:\ICT\bid-intel\frontend` 执行 `npm run dev`，用 Chrome 或 Edge 打开应用，并选择包含较长页面和长公告详情的数据集。
2. 页面滚到顶部，从关系线索打开一条公告详情。在开发者工具控制台运行：

   ```js
   (() => {
     const rect = document.querySelector('.evidence-dialog').getBoundingClientRect()
     return {
       dialogCenter: [rect.left + rect.width / 2, rect.top + rect.height / 2],
       viewportCenter: [window.innerWidth / 2, window.innerHeight / 2],
     }
   })()
   ```

   两组坐标应基本相同；详情内容应能在弹层内独立滚动，背景页面不应跟随滚轮移动。
3. 关闭弹层并确认页面回到打开前的滚动位置、焦点回到触发按钮。再滚到长页面中段重复打开，确认详情仍以当前浏览器视口为中心。
4. 分别验证关闭按钮、点击遮罩、Escape 关闭；打开“查看证据片段”后，验证片段二级弹层也居中、内容可滚动，关闭后焦点回到其入口。
