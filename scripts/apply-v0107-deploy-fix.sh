#!/bin/bash
# V0.107 deploy fix (option C): 修 systemd gold-etf-analyzer.service 的 uv run rebuild bug
# 改 ExecStart 从 `uv run uvicorn` 到 `.venv/bin/python -m uvicorn` (与原 428768 一致)
# 需要 sudo 因为要写 /etc/systemd/system/

set -e
UNIT=/etc/systemd/system/gold-etf-analyzer.service
BAK=/etc/systemd/system/gold-etf-analyzer.service.bak-v0106
NEW=/home/surui/gold-etf-analyzer/deploy/systemd/gold-etf-analyzer.service

echo "[1/6] 备份原 unit..."
sudo cp "$UNIT" "$BAK"
echo "  → $BAK"

echo "[2/6] 部署新 unit..."
sudo cp "$NEW" "$UNIT"
echo "  → $UNIT"
echo "  diff:"
sudo diff "$BAK" "$UNIT" | head -20

echo "[3/6] 重载 systemd 配置..."
sudo systemctl daemon-reload

echo "[4/6] 停止旧 uvicorn (root oneshot + systemd 失败重试)..."
# 旧 oneshot 进程 (428768 / 428807) 启动于 10/18 20:41, 跑的是 V0.106.2 代码
sudo kill 428768 428807 2>/dev/null || true
sudo systemctl stop gold-etf-analyzer || true
sleep 3

echo "[5/6] 启动新 systemd 服务..."
sudo systemctl start gold-etf-analyzer
sleep 5

echo "[6/6] 验证..."
# V0.110.0：验证宏观因子手动校准端点。**这一条能区分"新进程真的起来了"** ——
# 旧进程上该端点返回 404，而 static/*.html 是直接读磁盘的、改完即生效，
# 所以页面早就显示了卡片、后端却还是旧的（用户报「保存失败：Not Found」）。
MO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  "http://127.0.0.1:8888/api/v1/settings/macro-overrides")
echo "  GET /api/v1/settings/macro-overrides → HTTP $MO_CODE"
if [ "$MO_CODE" = "200" ]; then
  echo "  → 后端已是新版（V0.110.0 端点存在），手动校准可保存"
else
  echo "  → ⚠️  仍是 $MO_CODE：后端没换成新代码，页面会显示「后端尚未部署」说明块"
fi
# 保留 V0.107 的原有验证
curl -s "http://127.0.0.1:8888/api/v1/news-feed/daily?date=2026-10-19" | head -1
echo ""
echo "  systemd status:"
systemctl status gold-etf-analyzer --no-pager | head -10
echo ""
echo "✅ 完成！浏览器地址：http://192.168.0.204:8888/weights"
echo "   按 Ctrl+Shift+R 硬刷一次让 SW 升到 v0.110.0（否则会拿到缓存的旧 weights.html）"
