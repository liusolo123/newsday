# Newsday 网站部署与回滚手册

本手册用于在一台干净的 Linux 服务器部署 FastAPI、PostgreSQL、Nginx 与 systemd。命令中的 `example.com`、版本号、数据库密码和真实 Webhook 都是占位符，必须替换；本仓库不会自动改动生产服务器或向真实群发送消息。

## 1. 上线前准备

1. 在本地运行 `make check`，确认准备发布的 Git 提交已固定。
2. 准备已解析到服务器的域名；只对公网开放 80/443，绝不公开应用端口 18000。
3. 安装 Python 3.12、[uv](https://docs.astral.sh/uv/)、PostgreSQL 16、Nginx、Certbot 和 PostgreSQL client（含 `pg_dump`、`pg_restore`）。
4. 创建非 root 的 `newsdigest` 用户、`/opt/newsday` 应用目录，以及仅该用户可写的备份目录：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin newsdigest
sudo install -d -o newsdigest -g newsdigest -m 0750 /opt/newsday
sudo install -d -o newsdigest -g newsdigest -m 0700 /var/lib/newsday/backups/postgresql
```

创建仅供本项目使用的 PostgreSQL 数据库和用户。应用连接串示例为：

```text
postgresql+psycopg://newsdigest:数据库密码@127.0.0.1:5432/newsdigest
```

数据库账户只应拥有 `newsdigest` 数据库的权限；备份目录不保存 `.env`，也不应被 Web 服务器读取。同机备份不是异机灾备，应在运维系统另行安排加密的异机副本。

## 2. 代码、依赖与密钥

把已审阅的代码放入 `/opt/newsday`，并以 `newsdigest` 用户创建环境：

```bash
cd /opt/newsday
sudo -u newsdigest uv venv --python 3.12 .venv
sudo -u newsdigest uv pip sync --python .venv/bin/python requirements.lock
```

复制 `.env.example` 为 `/etc/newsday/newsday.env`，目录设为 `0750`、文件设为 `0640`，所有者为 `root:newsdigest`。必须设置：

- `DATABASE_URL`、`APP_ENV=production`
- `APP_SESSION_SECRET`、`INVITE_LOOKUP_KEY`、`WEBHOOK_ENCRYPTION_KEY`
- `DEEPSEEK_API_KEY`、`ADMIN_USERNAMES`
- `POSTGRES_BACKUP_DIR=/var/lib/newsday/backups/postgresql`

`ALERT_FEISHU_WEBHOOK` 为可选项，用于备份和保留任务的非敏感失败告警。所有密钥必须是新生成的高熵值，不能提交 Git，也不能出现在服务日志或工单中。

## 3. PostgreSQL 迁移、备份与恢复演练

每次迁移前先执行一次备份；该命令默认 dry-run，只有 `--apply` 会写入文件：

```bash
cd /opt/newsday
sudo -u newsdigest bash -c 'set -a; . /etc/newsday/newsday.env; set +a; exec /opt/newsday/.venv/bin/python -m app.postgres_backup_cli --apply'
sudo -u newsdigest bash -c 'set -a; . /etc/newsday/newsday.env; set +a; exec /opt/newsday/.venv/bin/python -m alembic upgrade head'
sudo -u newsdigest bash -c 'set -a; . /etc/newsday/newsday.env; set +a; exec /opt/newsday/.venv/bin/python -m alembic current'
```

备份为仅应用用户可读的 PostgreSQL custom-format `.dump` 文件，按文件修改时间保留 14 天。验证“前一版本备份能升级”的安全流程是：**不能在生产库上试验**，而是在临时数据库还原旧版本备份后运行目标版本迁移：

```bash
sudo -u postgres createdb newsday_migration_rehearsal
sudo -u newsdigest pg_restore --clean --if-exists --no-owner \
  --dbname=newsday_migration_rehearsal /var/lib/newsday/backups/postgresql/newsday-YYYYMMDDTHHMMSSZ.dump
DATABASE_URL='postgresql+psycopg://newsdigest:密码@127.0.0.1:5432/newsday_migration_rehearsal' \
  sudo -u newsdigest /opt/newsday/.venv/bin/python -m alembic upgrade head
sudo -u postgres dropdb newsday_migration_rehearsal
```

保留本次演练的 `alembic current`、`pg_restore` 和升级命令退出码；任一失败都不得继续发布。

## 4. systemd 与 Nginx

`ops/systemd` 中包含 Web、抓取、任务创建、任务发送、七天保留和每日 PostgreSQL 备份单元。所有服务以 `newsdigest` 运行、使用 `/etc/newsday/newsday.env`、禁止提权并限制文件系统访问。复制文件后先检查路径、用户与备份目录，再启用：

```bash
sudo cp /opt/newsday/ops/systemd/news-*.service /opt/newsday/ops/systemd/news-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-web.service
sudo systemctl enable --now news-schedule.timer news-dispatch.timer news-ingest.timer news-retention.timer news-backup.timer
sudo systemctl status news-web.service news-backup.service
sudo systemctl list-timers 'news-*'
```

`ops/nginx/newsday-bootstrap.conf` 是首次签发证书时的临时 HTTP 配置；将每个 `example.com` 改为真实域名、放入 Nginx include 目录后检查并启用。创建 `/var/www/certbot` 后签发证书，再以最终的 `ops/nginx/newsday.conf` 替换临时文件（同样替换所有域名），最后检查并重载：

```bash
sudo install -d -o root -g root -m 0755 /var/www/certbot
sudo install -m 0644 /opt/newsday/ops/nginx/newsday-bootstrap.conf /etc/nginx/conf.d/newsday.conf
# 将 /etc/nginx/conf.d/newsday.conf 中每个 example.com 改为真实域名。
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d example.com
sudo install -m 0644 /opt/newsday/ops/nginx/newsday.conf /etc/nginx/conf.d/newsday.conf
# 再次将每个 example.com 改为同一个真实域名。
sudo nginx -t && sudo systemctl reload nginx
```

最终 Nginx 模板会将 HTTP 重定向到 HTTPS，设置证书路径、转发 `Host`/真实 IP/协议头到仅监听 `127.0.0.1:18000` 的应用，限制请求体为 1 MiB，并添加防嗅探、禁止嵌入、Referrer 与 Permissions Policy 响应头。若证书先于应用签发，可临时使用 `ops/nginx/newsday-holding.conf` 返回 503，绝不可把新域名误代理到其他本机服务。证书续期后应执行 `nginx -t && systemctl reload nginx`。

## 5. 上线验收

以下项目必须在目标服务器逐项记录结果：

1. 本机检查 `curl -fsS http://127.0.0.1:18000/healthz` 与 `curl -fsS http://127.0.0.1:18000/readyz`；后者同时验证配置与数据库。
2. 访问 HTTPS 域名，确认 80 自动跳转、证书有效，且 18000 不可从公网访问。
3. 手动运行一次 `app.worker_cli ingest --config /opt/newsday/config.json`，确认新闻进入池中。
4. 用隔离的飞书群和企业微信群各保存并执行一次测试 Webhook；确认两方都收到消息，且不把真实 Webhook 写入日志。
5. 创建一条测试订阅和一个未来时间点，确认 `news-schedule` 生成任务、`news-dispatch` 投递一次且记录状态正确；随后删除测试订阅或禁用目标。
6. 手动执行 `app.postgres_backup_cli --apply`，检查权限为 `0600`，并在非生产临时库完成一次 `pg_restore`。

排障时使用 `journalctl -u news-web.service -f`、`journalctl -u news-ingest.service -n 100`、`journalctl -u news-dispatch.service -n 100` 与 `journalctl -u news-backup.service -n 100`。`/healthz` 只代表 Web 进程存活，不能替代上述端到端验收。

## 6. 回滚与故障通知

先暂停未来投递，保留日志和出错的备份文件；不要边回滚边继续发送：

```bash
sudo systemctl stop news-schedule.timer news-dispatch.timer news-ingest.timer news-retention.timer
sudo systemctl stop news-web.service
```

若数据库迁移或应用版本失败，按以下顺序处置：

1. 记录故障时间、当前 Git revision、`alembic current` 与相关 journal；通过 `ALERT_FEISHU_WEBHOOK` 或既定值班渠道发出不含密钥和正文的故障通知。
2. 将代码恢复到上一个已验证 release revision，重新用该 revision 的 `requirements.lock` 同步依赖；只有经过演练的降级迁移才可执行，未知迁移一律改为数据库恢复。
3. 在停机状态下将**迁移前**备份恢复到目标数据库：`pg_restore --clean --if-exists --no-owner --dbname=newsday /安全路径/备份.dump`；再以旧版本执行健康检查。
4. 重新启动 Web，先执行 `/readyz`，再按需逐个启用定时器，最后通知故障已恢复及可能重复/遗漏的投递范围。

如密钥或 Webhook 泄露，立即暂停相关 timer、撤销平台机器人地址并更新环境文件。轮换 `APP_SESSION_SECRET` 会使会话失效，轮换 `INVITE_LOOKUP_KEY` 会使旧邀请码不可验证。当前版本没有“旧/新密钥同时解密”的迁移机制；轮换 `WEBHOOK_ENCRYPTION_KEY` 会使旧加密凭据不可读，因此必须要求用户重新保存并测试 Webhook，不能在未通知用户时直接替换该密钥。完成处理后 `systemctl daemon-reload`、重启 Web，并保留审计记录。

涉及真实迁移、密钥轮换、systemd 启用、Nginx 改动、数据库恢复或向真实群发送消息，都需要在服务器维护窗口内由拥有权限的人员确认后执行。
