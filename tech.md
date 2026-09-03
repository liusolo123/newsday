# 个性化新闻订阅网站技术方案

版本：v1.0  
状态：首版实施方案

## 1. 技术选型结论

首版在现有阿里云单台 Linux 服务器上采用**模块化单体应用**：一个 Python 代码库、一个 Web 服务、一个新闻处理 worker 和一个投递调度 worker。它能直接复用已有的新闻抓取、去重、DeepSeek 中文润色与飞书发送逻辑，同时避免在首版过早引入微服务、消息队列或前后端双仓库的运维成本。

| 范围 | 采用技术 | 选择原因与实际职责 |
| --- | --- | --- |
| 运行时 | Python 3.12、uv、虚拟环境 | 与现有脚本一致；用锁定的依赖文件保证部署可复现。 |
| Web 后端 | FastAPI、Pydantic v2、Uvicorn | 提供页面、表单接口、管理接口和健康检查；Pydantic 负责输入、时间和数量的严格校验。 |
| 页面 | Jinja2、HTMX、少量原生 CSS | 首版以服务端渲染为主；表单分步校验和局部刷新无需维护独立 SPA 或 API 状态层。 |
| 数据库 | PostgreSQL 16、SQLAlchemy 2、Alembic | 支持事务、行级锁、可靠的定时任务领取与多用户数据；Alembic 管理可回滚的表结构迁移。 |
| 身份与安全 | argon2-cffi、cryptography（AES-256-GCM）、安全 Cookie | 密码、邀请码与恢复码只存 Argon2id 哈希；Webhook 在应用层加密后再入库。 |
| 新闻处理 | 现有 `finnews` 模块重构为服务层，requests/feedparser/BeautifulSoup/DeepSeek API | 继续使用已经验证的新闻源和中文润色策略；将文件产物改为持久化新闻池与可追踪的处理记录。 |
| 定时与任务 | PostgreSQL 任务表、独立 Python worker、systemd | 每分钟事务性领取到期投递任务；不为每个用户创建 cron，且不依赖 Redis/Celery。 |
| 发送适配 | `DestinationSender` 抽象、飞书/企业微信实现 | Webhook 测试、正式投递和失败重试走同一接口；未来 QQ 只新增适配器。 |
| Web 入口 | Nginx、Let's Encrypt、systemd | Nginx 终止 HTTPS 并反向代理；应用与两个 worker 作为独立服务自动拉起。 |
| 可观测性 | structlog/标准 logging、PostgreSQL 投递记录、现有运维脚本 | 记录结构化事件、发送状态、失败原因和 DeepSeek token；日志轮转、数据库备份和七天清理沿用并扩展现有机制。 |
| 测试与质量 | pytest、HTTPX TestClient、factory fixtures、Ruff | 覆盖验证规则、加密、任务去重、重试和发送适配器；提交前运行快速静态检查与相关测试。 |

首版**不采用** React/Vue、Redis、Celery、Docker 编排或 Kubernetes。它们在用户量和任务吞吐尚未明确时会显著增加复杂度；数据量或并发增长后，任务表接口可以再接入 Redis/Celery，而不改变页面、数据模型或发送适配器。

## 2. 代码与进程组织

在现有仓库中逐步形成以下结构。旧的顶层脚本在迁移期间保留为兼容入口，最终只调用对应服务层，避免两套新闻逻辑分叉。

```text
app/
  main.py                 # FastAPI 应用、路由注册、依赖注入
  web/                    # 首页、分类页、订阅向导、控制台、管理页
  auth/                   # 密码、会话、恢复码、邀请码、限流与 CSRF
  models/                 # SQLAlchemy ORM 模型
  services/
    news.py               # 抓取结果入库、分类、去重、新闻池查询
    polish.py             # DeepSeek V4 Flash/Pro 中文润色与结果缓存
    subscriptions.py      # 配置校验、保存和变更生效规则
    deliveries.py         # 生成、领取、投递和重试任务
    destinations.py       # 飞书、企业微信及未来 QQ 适配器
  workers/
    ingest.py             # 定期抓取、分类、润色与清理
    dispatch.py           # 每分钟扫描并处理到期投递任务
  templates/              # Jinja2 模板
  static/                 # CSS 与少量浏览器脚本
finnews/                  # 现有抓取、筛选、标准化逻辑，逐步成为可复用库
alembic/                  # PostgreSQL schema migrations
tests/
```

运行中的常驻单元为：

1. `news-web.service`：Gunicorn（Uvicorn worker）承载 FastAPI；仅响应 HTTP 请求。
2. `news-ingest.service`：每 2 小时运行抓取、标准化、分类和去重；不在入池时调用 AI 润色。
3. `news-dispatch.service`：每分钟扫描并投递到期任务；它可按需启动多个实例，靠数据库锁避免重复发送。
4. `nginx.service`：HTTPS、静态文件、反向代理及请求大小限制。

服务器时区可以保持系统默认，但应用中所有用户可见时间均使用 `Asia/Shanghai`。数据库时间统一存为 UTC 的 `timestamptz`；仅在创建当天计划和页面展示时转换为北京时间。

## 3. 数据库实现

PostgreSQL 是网站的唯一业务真相来源。SQLite 的历史新闻可以通过一次性迁移导入 `news_items`，之后不再作为 Web 业务数据库。原始抓取 JSON、完整个性化正文和运行日志仍属于可清理的文件产物，而不是长期业务数据。

### 3.1 主要表

| 表 | 关键字段与约束 | 实现要点 |
| --- | --- | --- |
| `users` | `id`、唯一 `username`、`password_hash`、`recovery_code_hash`、`status` | 用户名使用大小写不敏感唯一索引；密码和恢复码用 Argon2id 哈希。 |
| `auth_sessions` | `user_id`、`token_hash`、`expires_at`、`revoked_at` | Cookie 内只放随机不透明 token；数据库只存其哈希，便于登录退出、改密和管理员撤销。 |
| `invite_codes` | `id`、`lookup_hash`、`secret_hash`、`enabled`、`max_uses`、`used_count` | `lookup_hash` 是服务端密钥 HMAC，供快速定位；实际值再以 Argon2id 验证，邀请码不存明文。 |
| `subscriptions` | `user_id`、`enabled`、`timezone`、`updated_at` | 每个用户首版只允许一个有效订阅，时区固定为 `Asia/Shanghai`。 |
| `subscription_categories` | `subscription_id`、`category`、`item_limit` | 唯一约束 `(subscription_id, category)`；服务端限制分类为预设十类、每类 5～10 条。 |
| `schedules` | `subscription_id`、`local_time`、`enabled` | 唯一约束 `(subscription_id, local_time)`；事务中校验每个订阅最多 3 条。 |
| `destinations` | `subscription_id`、`kind`、`webhook_ciphertext`、`webhook_nonce`、`key_version`、`verified_at` | `kind` 首版仅 `feishu`、`wecom`；仅测试成功后填写 `verified_at` 并允许启用。 |
| `news_items` | `source`、`canonical_url`、`url_hash`、`title`、`summary_zh`、`category`、`tags`、`score`、`published_at` | `url_hash` 唯一，完成跨源去重；一条新闻一个主分类，标签使用 JSONB。 |
| `news_polishes` | `news_item_id`、`model`、`prompt_version`、`content_zh`、`usage_json` | 唯一约束 `(news_item_id, prompt_version)`；缓存润色结果，避免按用户重复调用模型。 |
| `delivery_jobs` | `id`、`subscription_id`、`destination_id`、`scheduled_for`、`status`、`attempts`、`locked_at`、`idempotency_key` | 唯一约束 `(subscription_id, destination_id, scheduled_for)`，这是防重复投递的核心。 |
| `delivery_items` | `delivery_job_id`、`news_item_id`、`position` | 保存本次实际选择的新闻，使重试和发送记录可复现。 |
| `delivery_attempts` | `delivery_job_id`、`attempt_no`、`started_at`、`finished_at`、`status`、`error_code` | 不保存 Webhook、完整请求体或新闻正文；状态与错误可按策略长期留存。 |

建模时为 `news_items(category, published_at DESC)`、`delivery_jobs(status, scheduled_for)`、`delivery_jobs(subscription_id, scheduled_for)` 和 `delivery_attempts(delivery_job_id)` 建立索引。数据库迁移必须用 Alembic 生成、审阅并在空库和升级路径上测试。

### 3.2 凭据和密钥

环境文件只存部署密钥，权限为 `0600`，并且从不提交：`DATABASE_URL`、`APP_SESSION_SECRET`、`WEBHOOK_ENCRYPTION_KEY`、`INVITE_LOOKUP_KEY`、DeepSeek key 和告警 Webhook。

- `WEBHOOK_ENCRYPTION_KEY` 使用 32 字节密钥，以 AES-256-GCM 加密每个 Webhook；每条记录存独立 nonce 与密钥版本。
- 页面只展示平台、验证时间和脱敏地址（例如域名与末尾少量字符）；解密仅发生在测试或发送进程内存中。
- 密码、恢复码和邀请码验证使用 Argon2id；不得使用可逆加密代替密码哈希。
- 所有修改状态的表单采用 CSRF token；登录、邀请码验证和测试发送按 IP 与用户名/邀请码限流。
- HTTP Cookie 设为 `HttpOnly`、`Secure`、`SameSite=Lax`；生产环境只允许 HTTPS。

## 4. 新闻处理和个性化实现

### 4.1 公共新闻池

`news-ingest` 每 2 小时执行以下流程：

```text
现有数据源适配器
  → 标准化标题、链接、来源、发布时间
  → 以 canonical URL / 标题相似度去重
  → 规则分类、标签和评分
  → 写入 news_items
  → 保存原始材料，等待实际投递时再按选中的新闻调用中文润色
```

分类首先使用可审阅的关键词/来源规则，无法确认时归入“科技”或不入池；不在首版引入不可解释的自动分类模型。时政、财经、社会热搜附带 `source_trust` 或核验状态；页面和消息模板据此展示来源/风险提示。每 2 小时入池不调用 AI；仅在实际投递前，对本次选中的新闻使用 `deepseek-v4-flash` 润色，并以 `deepseek-v4-pro` 修复失败项目。润色结果按新闻和提示词版本缓存，避免同一条新闻在后续投递重复调用。

分类选择采用以下确定规则：按用户勾选分类分别按评分和发布时间取所设数量，随后跨分类以 `url_hash` 和标题相似键全局去重；若新闻不足，可少于目标数量并在消息中明确提示，不用无关新闻填充。最终条目数在配置保存和任务创建两处均校验为不超过 50 条。

### 4.2 到期任务和幂等投递

`news-dispatch` 每分钟以北京时间计算每个启用订阅当天的各个 `local_time`，并在一个数据库事务内创建缺少的 `delivery_jobs`。用户修改配置只影响未来尚未创建或尚未领取的任务；暂停、取消订阅会取消未开始任务。

worker 使用类似以下的事务性领取方式：

```sql
SELECT id FROM delivery_jobs
WHERE status IN ('pending', 'retrying') AND next_attempt_at <= now()
ORDER BY scheduled_for
FOR UPDATE SKIP LOCKED
LIMIT 20;
```

领取后把任务标为 `sending`、写入锁定时间和唯一 `idempotency_key`；再在短事务外请求平台 Webhook。成功后写入 `sent` 和实际时间。网络超时、5xx 或平台限流走 1、5、15 分钟的指数退避，最多共 3 次；4xx 配置错误标为 `failed`，不再重试。worker 重启后，超时的 `sending` 锁会被回收为可重试状态。数据库唯一约束和领取锁共同保证多 worker、重启或重复扫描均不产生重复投递。

消息正文由 `delivery_items` 固定后再渲染。飞书和企业微信适配器都实现 `send_test()` 与 `send_delivery()`，以相同的超时、幂等键和错误映射处理；测试消息不创建正式投递任务。未来 QQ 官方机器人只增加一个实现，不改变订阅、任务和页面逻辑。

## 5. Web 页面和接口实现

页面优先以普通 HTML 表单完成，HTMX 仅用于邀请码即时校验、分类总量提示、Webhook 测试结果和控制台局部更新；JavaScript 被禁用时仍可提交完整表单。

| 页面/路由组 | 具体行为 |
| --- | --- |
| `/`、`/categories/{category}` | 公开展示已发布且经过基本处理的最新新闻；不显示任何用户或投递信息。 |
| `/subscribe/invite` | 输入邀请码并在短生命周期会话中标记验证成功，随后才允许进入注册。 |
| `/register`、`/login`、`/logout`、`/recovery` | 创建用户名密码、显示一次恢复码、建立/撤销会话、通过恢复码重置密码。 |
| `/dashboard` | 显示订阅状态、下一次发送时间、分类、平台脱敏信息和近 7 天投递记录。 |
| `/dashboard/subscription` | 保存分类、数量、最多三条时间、暂停/恢复与取消；服务端执行全部约束校验。 |
| `/dashboard/destination` | 展示获取机器人 Webhook 的平台指引、执行测试、加密保存与替换 Webhook。 |
| `/admin` | 仅管理员会话可访问：创建/停用/轮换邀请码、查看失败任务和重试/禁用处理。 |
| `/healthz`、`/readyz` | 给 Nginx 和 systemd/监控使用；后者检查 PostgreSQL 连接和关键密钥是否配置。 |

管理员不是通过公开用户名角色直接授予，而是在部署配置中显式列出管理员用户名或通过单独的初始管理员命令创建。所有管理动作写审计事件，但不记录邀请码明文、Webhook 或新闻正文。

## 6. 部署、保留与运维

生产部署使用一个非 root 的 `newsdigest` 系统用户。Nginx 只暴露 80/443，应用仅监听 `127.0.0.1:8000`。证书由 Certbot 自动续期；systemd 对 Web 与 worker 设置重启策略、资源上限和仅包含必要环境变量的 `EnvironmentFile`。

PostgreSQL 以本机服务开始，数据库用户仅拥有本应用数据库的权限。每日使用 `pg_dump` 生成压缩备份，保留 14 天；现有 `ops_maintenance.py` 会在迁移期间继续维护 SQLite 备份和日志，切换完成后改为 PostgreSQL 备份实现。备份目录权限设为仅应用/管理员可读，且不包含 `.env`。重要数据的异机备份（如 OSS）作为上线前运维项，不把同机备份视为灾备。

七天清理由每日独立维护任务执行：删除超过 7 个自然日的原始抓取文件、`news_items` 的正文/摘要、`news_polishes`、`delivery_items` 的渲染快照及完整发送载荷；保留不含正文的 `delivery_jobs`/`delivery_attempts` 状态、时间和错误码。删除采用带日期边界的批处理和 dry-run 模式，并记录删除数量；任务失败会沿用现有飞书告警。

发布流程为：在本地运行迁移与测试 → 备份数据库 → 部署代码与锁定依赖 → 执行 `alembic upgrade head` → 重启 Web/worker → 调用 `/readyz` 并完成一条测试 Webhook 发送。数据库迁移必须先在备份副本演练；涉及数据删除、密钥轮换或正式群发送的操作需单独确认。

## 7. 实施顺序与验收

1. **基础设施**：补充锁定依赖、环境变量模板、PostgreSQL/Alembic、基础 ORM 模型、迁移与 health check。
2. **新闻池迁移**：把当前 `finnews` 逻辑封装为服务，建立分类、公共新闻页、DeepSeek 缓存和七天清理。
3. **身份与订阅**：实现邀请码、用户名密码/恢复码、配置向导、Webhook 加密与飞书测试发送。
4. **可靠投递**：实现任务生成、行锁领取、重试、投递记录、企业微信适配器和控制台。
5. **上线加固**：Nginx/HTTPS/systemd、PostgreSQL 备份、限流/审计、监控告警及端到端验收。

每一阶段至少验证：迁移可升级、关键模型约束有效、敏感字段不出现在日志、失败可重试且不会重复投递。首版最终以 `WEBSITE_DESIGN.md` 第 10 节的验收标准为准；本文件规定实现边界和技术路径，不代表已开始网站功能开发。
