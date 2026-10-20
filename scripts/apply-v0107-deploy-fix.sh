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

echo "[4/6] 停止旧 uvicorn (root oneshot + systemd)..."
# 旧 oneshot 进程 (428768 / 428807) 启动于 10/18 20:41, 跑的是 V0.106.2 代码
sudo systemctl stop gold-etf-analyzer 2>/dev/null || true
sudo kill 428768 428807 2>/dev/null || true
# ⚠ kill 之后**必须确认端口真的空了**再往下走：旧进程还占着 8888 时，新服务起来
# 会直接 "Address already in use" 退出，用户看到的是"部署完了但还是 404"。
for i in $(seq 1 15); do
  if ! ss -ltn 2>/dev/null | grep -q ':8888 '; then break; fi
  sleep 1
done
if ss -ltn 2>/dev/null | grep -q ':8888 '; then
  echo "  ⚠ 8888 仍被占用，旧进程可能没杀掉。请手工确认："
  echo "     sudo ss -ltnp | grep 8888   # 找占用者 PID"
  echo "     sudo kill -9 <PID>"
  exit 1
fi
echo "  → 8888 已释放"

echo "[5/6] 启动新 systemd 服务..."
sudo systemctl start gold-etf-analyzer

# 轮询到端点真的可用为止。固定 sleep 不够：启动失败的原因只在 journal 里
# （V0.110.0 就差点卡在 ModuleNotFoundError: No module named 'app'），
# 而页面上只会显示一个"后端尚未部署"的说明块，看不出真因。
MO_CODE=000
for i in $(seq 1 30); do
  MO_CODE=$(curl -s -m 2 -o /dev/null -w "%{http_code}" \
    "http://127.0.0.1:8888/api/v1/settings/macro-overrides" || echo 000)
  [ "$MO_CODE" = "200" ] && break
  sleep 1
done

echo "[6/6] 验证..."
echo "  GET /api/v1/settings/macro-overrides → HTTP $MO_CODE"
if [ "$MO_CODE" != "200" ]; then
  echo "  → ❌ 新服务没起来。下面是 journal 最后 25 行（**原因在这里**）："
  sudo journalctl -u gold-etf-analyzer -n 25 --no-pager | sed 's/^/     /'
  echo ""
  echo "  常见原因："
  echo "    · ModuleNotFoundError: No module named 'app' → unit 缺 Environment=PYTHONPATH=.../src"
  echo "    · Permission denied on data/ → ReadWritePaths 与实际数据目录不符"
  echo "    · Address already in use → 旧进程还占着 8888"
  exit 1
fi
echo "  → ✅ 后端已是 V0.110.0，手动校准可保存"

# 保留 V0.107 的原有验证
curl -s "http://127.0.0.1:8888/api/v1/news-feed/daily?date=2026-10-19" | head -1
echo ""
echo "  systemd status:"
systemctl status gold-etf-analyzer --no-pager | head -10
echo ""
echo "✅ 完成！浏览器地址：http://192.168.0.204:8888/weights"
echo "   按 Ctrl+Shift+R 硬刷一次让 SW 升到 v0.110.0（否则会拿到缓存的旧 weights.html）"
