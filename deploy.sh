#!/usr/bin/env bash
# 每日新闻早报 · 服务器一键部署脚本(Linux)
# 用法: 先把整个 newsdigest 目录传到服务器,然后:
#   bash deploy.sh /path/to/newsdigest
set -euo pipefail

APP_DIR="${1:-$HOME/newsdigest}"
cd "$APP_DIR"

echo "[1/4] 创建虚拟环境..."
python3 -m venv .venv

echo "[2/4] 安装依赖..."
.venv/bin/pip install -q -r requirements.txt

echo "[3/4] 注册定时任务(每天 08:00 北京时间)..."
# 自动判断服务器时区: CST(+8) 直接用 8 点,否则按 UTC 0 点(北京 8 点)
TZ_NAME=$(date +%Z)
if [ "$TZ_NAME" = "CST" ] || [ "$TZ_NAME" = "+0800" ]; then
  CRON_TIME="0 8 * * *"
  echo "     检测到服务器时区 $TZ_NAME, cron 时间 = 每天 08:00"
else
  CRON_TIME="0 0 * * *"
  echo "     检测到服务器时区 $TZ_NAME(非北京时间), cron 时间 = 每天 00:00 UTC (= 北京 08:00)"
fi
CRON_LINE="$CRON_TIME cd $APP_DIR && .venv/bin/python fetch_sources.py >> run.log 2>&1 && .venv/bin/python build_report.py >> run.log 2>&1 && .venv/bin/python send_feishu.py >> run.log 2>&1"
(crontab -l 2>/dev/null | grep -v "newsdigest" || true; echo "$CRON_LINE") | crontab -

echo "[4/4] 完成。"
echo ""
echo "下一步:"
echo "  1) 立即手动测试(不依赖 webhook):"
echo "       cd $APP_DIR && .venv/bin/python fetch_sources.py && .venv/bin/python build_report.py"
echo "  2) 配置飞书 webhook(推荐,给到 token 后再做):"
echo "       echo 'FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的token' > $APP_DIR/.env"
echo "     (.env 已加入代码支持,crontab 无需任何额外配置)"
echo "  3) 发送到飞书测试:"
echo "       cd $APP_DIR && .venv/bin/python send_feishu.py"
echo "  4) 查看运行日志:"
echo "       tail -f $APP_DIR/run.log"
echo "  5) 查看已注册的定时任务:"
echo "       crontab -l | grep newsdigest"
