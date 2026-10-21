#!/bin/bash
# V0.111.0 部署：报告存档（HTML 上传 + 元数据登记表）
#
# ⚠ 为什么需要 sudo：只有两条动作要 root —— 改 nginx 配置 + systemctl restart。
#    迁移本身以 surui 身份跑（data/ 是 surui 可写的）。
#
# ⚠ 为什么必须先迁移再重启：`/api/v1/reports/*` 每次请求都查 reports 表，
#    表不存在就是 OperationalError → 500。而 StaticFiles 是分裂脑：页面 HTML
#    改完即时生效，Python 路由冻在 uvicorn 进程内存里 —— 所以**在迁移之前
#    页面已经能看到「报告存档」，点进去却 404**，正是当前状态。
#
# 用法：  cd /home/surui/gold-etf-analyzer && bash scripts/apply-v0111-deploy.sh

set -euo pipefail
cd /home/surui/gold-etf-analyzer

echo "[1/5] 应用数据库迁移（reports 表）..."
# ⚠ 不打印 .env.prod 的任何值 —— 只 source，不 echo
set -a
# shellcheck disable=SC1091
. ./.env.prod
set +a
export PYTHONPATH=/home/surui/gold-etf-analyzer/src
.venv/bin/python -m alembic upgrade head
.venv/bin/python - <<'PY'
import sqlite3, os
url = os.environ["DATABASE_URL"]
path = url.split("///")[-1]
c = sqlite3.connect(path)
ok = "reports" in [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
print(f"  → reports 表{'已就位 ✓' if ok else '仍缺失 ✗'}（{path}）")
print("  → alembic:", c.execute("select * from alembic_version").fetchall())
raise SystemExit(0 if ok else 1)
PY

echo "[2/5] nginx 放开上传大小（默认 1MB，不放开超限直接 413）..."
sudo python3 - <<'PY'
import re, pathlib
p = pathlib.Path("/etc/nginx/sites-enabled/gold-etf-analyzer")
t = p.read_text(encoding="utf-8")
if "client_max_body_size" in t:
    print("  → 已存在，跳过")
else:
    m = re.search(r"^(\s*)server\s*\{", t, re.M)
    if not m:
        raise SystemExit("✗ 找不到 server { } 块，请手工加 client_max_body_size 20m;")
    indent = m.group(1) + "    "
    t = t[:m.end()] + f"\n{indent}client_max_body_size 20m;" + t[m.end():]
    p.write_text(t, encoding="utf-8")
    print("  → 已插入 client_max_body_size 20m;")
PY

echo "[3/5] 校验并重载 nginx..."
sudo nginx -t
sudo systemctl reload nginx

echo "[4/5] 重启后端（StaticFiles 分裂脑：Python 路由必须重启才生效）..."
# 预检：8888 上若有个**非 systemd 管的** uvicorn（有人手工接管过），
# systemctl restart 会起新实例时撞 "Address already in use" 而失败，
# 页面上只表现为"部署完了还是旧行为"。先说清楚，别让人猜。
OWNER=$(sudo ss -ltnp 2>/dev/null | grep ':8888 ' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -n "$OWNER" ]; then
  MAINPID=$(systemctl show gold-etf-analyzer.service -p MainPID --value 2>/dev/null || echo "")
  if [ "$OWNER" != "$MAINPID" ]; then
    echo "  ⚠ 8888 被 pid=$OWNER 占用，但它不是 systemd 的 MainPID($MAINPID)。"
    echo "    多半是有人手工起的 uvicorn。先处理掉，否则重启会撞端口："
    echo "      sudo ss -ltnp | grep 8888   # 确认占用者"
    echo "      kill $OWNER"
    exit 1
  fi
fi
sudo systemctl restart gold-etf-analyzer.service

# 轮询到端点真的可用为止。固定 sleep 不够：启动失败的真正原因只在 journal 里
# （V0.110.0 就差点卡在 ModuleNotFoundError: No module named 'app'）。
echo "[5/5] 验证..."
OK=0
for i in $(seq 1 30); do
  CODE=$(curl -s -m 2 -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/api/v1/reports || true)
  if [ "$CODE" = "200" ]; then OK=1; break; fi
  sleep 1
done

if [ "$OK" != "1" ]; then
  echo "✗ /api/v1/reports 在 30s 内没返回 200。最后一次 code=$CODE"
  echo "  排障：sudo journalctl -u gold-etf-analyzer -n 50 --no-pager"
  exit 1
fi

for pair in "/api/v1/reports 列表" "/api/v1/reports/categories 分类" "/api/v1/reports/stats 统计"; do
  set -- $pair
  printf "  %-28s -> %s\n" "$2" "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8888$1")"
done
printf "  %-28s -> %s\n" "/report-archive 别名" "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/report-archive)"
printf "  %-28s -> %s\n" "nginx 8889 /gold/" "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8889/gold/api/v1/reports)"

echo
echo "✅ 部署完成。浏览器端建议：强制刷新一次（Ctrl+Shift+R）——"
echo "   sw.js 已 bump 到 v0.111.0，旧缓存会在 activate 阶段被清掉，"
echo "   但已打开的标签页仍可能持有旧 JS。"
