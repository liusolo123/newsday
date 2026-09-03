# 每日新闻早报 · 服务器部署手册（方案 A：自己操作）

> 服务器：47.108.165.132（阿里云）｜ 部署目标：每天 08:00 自动抓取→组装→发飞书

---

## 第 0 步：确认能连上服务器

在你自己的电脑（Windows PowerShell / CMD / Git Bash 都行）执行：

```
ssh root@47.108.165.132
```

- 能登录 → 继续第 1 步。
- 连不上 → 检查：① ECS 控制台实例是否"运行中"；② 安全组入方向是否放行 22 端口；③ 是否改过 SSH 端口。

## 第 1 步：把代码传到服务器（三选一）

**方式 A（推荐，图形界面）：WinSCP**
1. 下载安装 WinSCP（https://winscp.net）
2. 新建会话：主机 `47.108.165.132`，用户名 `root`，填密码
3. 把本机 `newsdigest` 整个文件夹拖到服务器 `/root/` 下

**方式 B：命令行 scp（Windows 自带）**

在 Windows 命令行（PowerShell 或 CMD）执行：

```
scp -r C:\Users\liuso\WorkBuddy\2026-08-02-17-48-57\newsdigest root@47.108.165.132:/root/
```

**方式 C：上传压缩包（tar.gz 已备好，见工作区根目录 newsdigest.tar.gz）**

WinSCP 上传 `newsdigest.tar.gz` 到 `/root/`，然后服务器上执行：

```
cd /root && tar xzf newsdigest.tar.gz
```

> 三种方式任选其一，最终服务器上要有 `/root/newsdigest` 目录（内含 fetch_sources.py、deploy.sh 等）。

## 第 2 步：一键部署

SSH 登录服务器后执行：

```
cd /root/newsdigest && bash deploy.sh
```

脚本会自动：建虚拟环境 → 装依赖 → 注册 crontab（每天 08:00 北京时间，已自动判断时区）。定时流程只有在飞书发送成功后才执行日报清理，保留最近 7 个自然日。

## 第 3 步：手动测试（不需要 webhook 也能跑）

```
cd /root/newsdigest && .venv/bin/python fetch_sources.py && .venv/bin/python build_report.py
```

看到 `[ok] github_trending: 15 条` 等输出、最后 `校验通过` 即成功。早报文件在 `output/2026-08-02.md`。

## 第 4 步：配置飞书 webhook（等 token 到手后）

```
echo 'FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的token' > /root/newsdigest/.env
```

然后测试发送：

```
cd /root/newsdigest && .venv/bin/python send_feishu.py
```

飞书群里出现早报即成功。

## 第 5 步：验证定时任务

```
crontab -l | grep newsdigest
```

应看到每天 08:00（或 UTC 00:00）的执行行。日常查日志：

```
tail -f /root/newsdigest/run.log
```

清理范围仅包括 `output/YYYY-MM-DD.md`、旧版 `output/YYYY-MM-DD-llm.md`、`output/YYYY-MM-DD.selected.json` 和 `data/raw/YYYY-MM-DD.json`。默认命令只预演，确认列表后可显式执行：

```
cd /root/newsdigest && .venv/bin/python cleanup.py
cd /root/newsdigest && .venv/bin/python cleanup.py --apply
```

---

## 常见问题

| 问题 | 处理 |
| --- | --- |
| fetch 某源报错 | 正常降级：脚本会注明「暂未获取到」，不影响其他源（海外服务器抓微博可能失败，国内服务器抓 HN 可能走 Algolia 回退） |
| crontab 时间不对 | 检查服务器时区：`date`；必要时手动改 `crontab -e` |
| 飞书没收到 | 先跑 send_feishu.py 看报错；确认 .env 已创建且 token 正确；确认机器人没被群主关闭 |
| 想手动发一份 | `cd /root/newsdigest && .venv/bin/python send_feishu.py` |
