# 外网评审部署说明

评委要求“直接在提供的网站上测试”时，应提供一个能从评委网络访问的 HTTPS 地址。已有博客域名可以继续保留，建议使用独立子域名，例如 `review.ru00ys-lab.com`，不要把博客根域名改到本系统。

## 先确认托管能力

域名只负责解析，不提供 Python 后端运行环境。当前 `ru00ys-lab.com` 的公开 DNS 使用 Cloudflare，博客响应头显示 GitHub/Cloudflare 静态托管特征。静态博客托管不能直接运行 FastAPI、SQLite 和上传任务。

需要在以下两种方案中选择一种：

1. **VPS/云服务器（推荐）**：服务器持续运行 FastAPI 和 Nginx，子域名的 A 记录指向服务器公网 IPv4。评委访问 HTTPS 子域名时，Nginx 提供前端并将 `/api/` 转发到本机 FastAPI。
2. **Cloudflare Tunnel（临时演示）**：在一直开机的演示电脑运行 FastAPI、前端和 `cloudflared`，创建一条隧道并将子域名指向隧道。电脑关机、休眠、断网或进程停止时，评委就无法访问。

博客托管商若只提供静态文件上传，不能替代上述运行环境。不要将 SQLite 数据库或评审密码上传到博客仓库。

## VPS 部署步骤

以下示例以 Ubuntu 22.04/24.04、子域名 `review.ru00ys-lab.com` 为例。实际服务器地址、用户名和域名由团队填写。

演示服务器建议至少 2 vCPU、2 GiB 内存、30 GiB 磁盘及固定公网 IPv4。1 GiB 内存只能作为精简部署选择：前端构建后由 Nginx 提供，FastAPI 保持单进程，使用 SQLite 与在线模型服务，避免同时运行 Neo4j、本地模型或批量 OCR，并配置交换空间缓冲峰值。“非中国优化”线路需从评委所在网络验证连接速度；标称公网带宽不能保证国内访问质量。当前仅完成 Windows 本机验收，未实测该服务器规格。

1. 在 Cloudflare DNS 增加一条记录：

   | 类型 | 名称 | 内容 | 代理 |
   |---|---|---|---|
   | A | `review` | `<服务器公网IPv4>` | Proxied（橙云） |

   若使用 IPv6，再单独增加 AAAA；没有 IPv6 时不要填写伪造地址。Cloudflare SSL/TLS 选择 **Full (strict)**，服务器证书使用 Let’s Encrypt。

2. 将提交包中的 `01_工程源码` 上传服务器，复制官方全量数据库到后端数据目录，例如：

   ```bash
   sudo mkdir -p /opt/bid-intel/backend/.data/datasets
   sudo cp /path/to/08_任务三自助上传与下载/运行数据库/official.sqlite \
     /opt/bid-intel/backend/.data/datasets/6e032fb74bd345e29989e4f86e195920.sqlite
   ```

   不把原始官方语料、API Key 或 `.env` 提交到公开 Git 仓库。

3. 在 `/opt/bid-intel/backend/.env` 配置生产环境（账号密码用随机值，不写入文档）：

   ```dotenv
   DATABASE_PATH=.data/bidintel.db
   AUTH_ENABLED=true
   AUTH_USERNAME=reviewer
   AUTH_PASSWORD=<至少12位随机密码>
   AUTH_SECRET_KEY=<至少32字节随机密钥>
   AUTH_COOKIE_SECURE=true
   CORS_ALLOWED_ORIGINS=https://review.ru00ys-lab.com
   EXTRACTION_MODE=rules
   ```

   评委只需要查看已经入库的官方数据和任务三规则导入时，不配置 `MODEL_API_KEY`；需要模型提取时再在服务器私有环境变量中配置允许的模型服务。

4. 安装 Python 3.11–3.13、Node.js 及项目依赖，启动 FastAPI：

   ```bash
   cd /opt/bid-intel/backend
   python3 -m venv .venv
   .venv/bin/pip install -e .
   .venv/bin/python -c "from pathlib import Path; from app.storage import initialize; initialize(Path('.data/datasets/6e032fb74bd345e29989e4f86e195920.sqlite'))"
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   前端用与评审域名一致的 API 基址构建：

   ```bash
   cd /opt/bid-intel/frontend
   VITE_API_BASE=https://review.ru00ys-lab.com npm run build
   ```

5. Nginx 提供 `frontend/dist`，并将 `/api/` 反代到 `127.0.0.1:8000`。随后用 Certbot 配置 HTTPS。必须验证：

   - `https://review.ru00ys-lab.com/api/v1/health` 返回 `status: ok`；
   - 登录、刷新后会话仍在；
   - 选择“官方全量·修复后”数据集；
   - 上传一条独立测试公告、下载三表结果、查询标的和供应商；
   - 退出后受保护 API 返回 401。

## 无服务器时的临时方案

可以在本机运行 FastAPI 和前端，再用 Cloudflare Tunnel 映射到 `review.ru00ys-lab.com`。这只能作为临时评审方案：本机必须持续开机、保持网络连接并运行服务；应先在另一台网络中的电脑测试登录、上传和下载。此方案不应在材料中写成稳定公网部署。

## 交付给评委的信息

最终提交材料中只放以下信息：

- 评审地址：`https://review.ru00ys-lab.com`（部署完成后替换为实际子域名）；
- 用户名：`reviewer`；
- 密码：通过受控渠道单独发送，不写进公开仓库；
- 操作：登录 → 选择“官方全量·修复后” → 查询/上传 → 下载标准结果表；
- 服务状态和测试时间。

在服务器或 Tunnel 尚未实际运行、第二台设备尚未验证前，不要把占位地址写成“已部署”。
