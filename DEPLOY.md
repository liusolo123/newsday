# Newsday 网站部署手册

本手册对应当前网站架构：FastAPI 网站、PostgreSQL、每两小时抓取、每分钟创建与发送投递任务，以及每日七天保留清理。以下内容是部署清单，**不会由代码自动在服务器上执行**。

## 1. 上线前准备

1. 在本地通过完整测试，并确认 Git 提交已完成。
2. 准备域名和 HTTPS；不要直接公开应用的 8000 端口。
3. 在服务器创建非 root 的 `newsdigest` 用户与 `/opt/newsday` 目录。
4. 安装 Python 3.11+、PostgreSQL 16、Nginx 和 Certbot；创建仅供本项目使用的 PostgreSQL 数据库与用户。

数据库地址示例：

```text
postgresql+psycopg://newsdigest:数据库密码@127.0.0.1:5432/newsdigest
```

## 2. 代码与密钥

将已审阅的代码放入 `/opt/newsday`，然后创建 Python 虚拟环境并安装依赖：

```bash
cd /opt/newsday
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

复制 `.env.example` 为 `/etc/newsday/newsday.env`，设为仅管理员和应用用户可读（建议 `chmod 640`）。必须填写：

- `DATABASE_URL`
- `APP_ENV=production`
- `APP_SESSION_SECRET`
- `INVITE_LOOKUP_KEY`
- `WEBHOOK_ENCRYPTION_KEY`
- `DEEPSEEK_API_KEY`
- `ADMIN_USERNAMES`

所有密钥都应为新生成的高熵值；不要将 `/etc/newsday/newsday.env`、真实 Webhook 或数据库密码提交到 Git。

## 3. 数据库迁移与验证

首次上线或每次更新数据库结构前，先备份数据库，再运行：

```bash
cd /opt/newsday
set -a; . /etc/newsday/newsday.env; set +a
.venv/bin/python -m alembic upgrade head
```

启动网站前可用下列命令检查迁移状态：

```bash
.venv/bin/python -m alembic current
```

## 4. systemd 与 Nginx

仓库中的 `ops/systemd` 包含以下单元：

- `news-web.service`：仅监听 `127.0.0.1:8000` 的网站服务。
- `news-schedule.timer`：每分钟创建到期投递任务。
- `news-dispatch.timer`：每分钟发送或重试到期任务。
- `news-ingest.timer`：每两小时抓取新闻；不调用 AI 润色。
- `news-retention.timer`：每日执行七天保留清理。

将这些文件复制到 `/etc/systemd/system/` 后，按实际路径和运行用户复核，再执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now news-web.service
sudo systemctl enable --now news-schedule.timer news-dispatch.timer news-ingest.timer news-retention.timer
sudo systemctl status news-web.service
sudo systemctl list-timers 'news-*'
```

`ops/nginx/newsday.conf` 是 Nginx 反向代理模板。部署前把 `example.com` 改为真实域名，验证配置后再启用 HTTPS：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. 上线验收

在服务器本机运行：

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

`/healthz` 仅表示 Web 进程存活；`/readyz` 还会检查必需配置与数据库连接。随后使用后台创建一个一次性邀请码、创建测试账号、保存一个测试 Webhook 并手动执行一次测试发送。正式发送前应确认测试群已收到消息。

日常排障可使用：

```bash
journalctl -u news-web.service -f
journalctl -u news-ingest.service -n 100
journalctl -u news-dispatch.service -n 100
```

涉及真实迁移、密钥轮换、systemd 启用、Nginx 改动或向真实群发送消息时，均应在执行前单独确认。
