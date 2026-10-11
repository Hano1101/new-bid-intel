# 评委操作指南

本指南按实际演示顺序介绍登录、导入、分析、证据追溯和人工复核。首次了解作品可先阅读 [`JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md)；安装和开发命令见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。

## 由演示负责人准备账号

在仓库根目录运行一次；再次运行会重置凭据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Configure-ReviewerAccount.ps1
```

脚本会生成密码和签名密钥，写入本机 `backend/.env`，并把账号保存在 Git 忽略的 `backend/.data/reviewer-credentials.txt`，不会将密码打印到终端。请通过受控渠道向评委提供账号，不把凭据写入 Git、录屏或公开画面。

如需手工配置，可在 `backend/.env` 设置：

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=reviewer
AUTH_PASSWORD=<项目组设置的密码>
AUTH_SECRET_KEY=<至少 32 字节随机值>
AUTH_SESSION_HOURS=8
AUTH_COOKIE_SECURE=false
```

配置后重启后端。HTTP 演示使用 `AUTH_COOKIE_SECURE=false`，HTTPS 部署使用 `true`。会话 Cookie 为 HttpOnly、SameSite=Strict，默认 8 小时过期。

## 启动和登录

完成依赖安装后，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-Demo.ps1 -Offline
```

打开启动脚本显示的分析台地址。本机默认使用 `http://localhost:5173`，局域网访问使用脚本显示的主机 IPv4 地址。输入评审账号，在数据集选择器中选择“离线演示样例（纯虚构）”。该模式会准备虚构样例并采用规则抽取，不调用在线模型。

如需配置网络访问、主机诊断或防火墙，请参阅 [LAN 部署操作说明](LAN_ACCEPTANCE.md)。分析台与 `/annotation.html` 共用会话；结束时可从页面顶部退出登录。

## 功能演示顺序

| 操作 | 观察内容 |
|---|---|
| 打开一条公告详情 | 标的字段、包号、采购单位、投标与中标记录，以及来源文件、定位、片段和警告 |
| 进入五类分析并设置筛选条件 | 各场景的结果、查询口径、项目/包计数、金额和实际分析后端 |
| 搜索采购单位、供应商或项目 | 同名结果区分、受控范围的 1-hop 关系网络、节点与边数量及截断提示 |
| 展开一张关系线索卡 | 统计指标、来源公告和提示；点击证据入口打开居中的公告详情 |
| 打开人工复核队列 | 数据质量信号、接受/修正/驳回操作，以及操作后的事件历史 |
| 打开已导入的公告版本记录 | 版本证据、公告与附件变化，以及版本间语义比较 |

关系线索帮助定位需要核查的材料，不自动认定违规行为。图搜索、分析和人工复核都沿用当前选择的数据集，切换数据集后请重新选择查询对象。

## 导入评审材料

单条导入可选择公告 HTML 与对应附件文件；批量处理可在服务器材料目录浏览器中选择目录，查看预检结果后创建任务。服务器目录由部署方通过 `INTAKE_ROOT` 配置，浏览器只展示该范围内的目录。批量任务支持进度查看、暂停、续跑和失败重试。

导入后先查看回执中的材料数量、解析结果和告警，再查看候选记录与关系分析。模型、混合、规则三条路线可按运行配置选择；规则和本地 OCR 流程无需在线模型。离线样例只用于展示交互，真实材料应在独立业务数据集中导入。

人工标注台用于对照原文整理 reviewed 数据；人工复核队列用于跟踪业务候选的核验与修正。团队已有的 24 条 reviewed 数据参与过开发调试，属于本地开发回归材料。

## 常见问题与结束演示

- `503 登录未配置`：检查 `.env` 中认证是否启用，用户名、密码和签名密钥是否完整，然后重启后端。
- 页面无法连接 API：确认主机的 `/api/v1/health` 可访问，检查前后端地址及端口；主机诊断可运行 `scripts/Test-LanDemo.ps1`。
- 登录后仍返回 `401`：前端和 API 应使用相同主机名，端口可以不同；清除旧 Cookie 后重新登录。
- 批量材料目录不可用：确认后端已配置 `INTAKE_ROOT`，服务账号对该目录有访问权限。
- 某个历史字段没有可用引用：详情会显示当前保存的证据状态；请对照原材料核验，系统不会补造来源。

结束演示后，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Stop-Demo.ps1
```

当前评审登录采用单账号轻量会话认证。面向互联网提供服务时，应在部署层配置 HTTPS、访问控制与组织要求的身份管理。
