#!/usr/bin/env bash
# V0.72.0 P3-b：Let's Encrypt 证书初始化脚本
# ────────────────────────────────────────────────────────────────
# 用法：
#   ./deploy/init-letsencrypt.sh --domain gold.example.com --email admin@example.com
#   ./deploy/init-letsencrypt.sh --domain gold.example.com --email admin@example.com --dry-run
#
# 流程：
#   1. dry-run 验证（用 certbot --dry-run）
#   2. 检查证书是否已签发（已存在 → 跳过）
#   3. 用 webroot 挑战签发
#   4. 启动 nginx 加载证书
#
# 幂等：多次执行安全（已签发时直接退出）

set -euo pipefail

DOMAIN=""
EMAIL=""
DRY_RUN=false
STAGING=false

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)  DOMAIN="$2"; shift 2 ;;
        --email)   EMAIL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --staging) STAGING=true; shift ;;
        -h|--help)
            echo "Usage: $0 --domain <domain> --email <email> [--dry-run] [--staging]"
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "ERROR: --domain and --email are required"
    exit 1
fi

# ── 路径 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CERTBOT_CONF="$PROJECT_ROOT/certbot/conf"
CERTBOT_WWW="$PROJECT_ROOT/certbot/www"

mkdir -p "$CERTBOT_CONF" "$CERTBOT_WWW"

# ── 临时下载 nginx 配置（占 80 端口；不需要 cert 已签发）──
echo "▶ Staging nginx for ACME challenge..."
docker run --rm -d \
    --name temp-nginx \
    -p 80:80 \
    -v "$CERTBOT_WWW:/var/www/certbot:ro" \
    -v "$PROJECT_ROOT/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    nginx:1.27-alpine >/dev/null
sleep 3

cleanup() {
    echo "▶ Cleaning up temp nginx..."
    docker stop temp-nginx >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── 1. Dry-run ──
if [[ "$DRY_RUN" == true ]]; then
    echo "▶ Dry-run certbot..."
    docker run --rm \
        -v "$CERTBOT_CONF:/etc/letsencrypt:rw" \
        -v "$CERTBOT_WWW:/var/www/certbot:rw" \
        certbot/certbot certonly \
            --webroot --webroot-path=/var/www/certbot \
            --domain "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email \
            --dry-run
    echo "✅ Dry-run OK"
    exit 0
fi

# ── 2. 已签发检查 ──
if [[ -f "$CERTBOT_CONF/live/$DOMAIN/fullchain.pem" ]]; then
    echo "✅ Certificate already exists for $DOMAIN"
    exit 0
fi

# ── 3. 正式签发 ──
echo "▶ Requesting certificate for $DOMAIN..."
STAGING_FLAG=""
[[ "$STAGING" == true ]] && STAGING_FLAG="--staging"

docker run --rm \
    -v "$CERTBOT_CONF:/etc/letsencrypt:rw" \
    -v "$CERTBOT_WWW:/var/www/certbot:rw" \
    certbot/certbot certonly \
        --webroot --webroot-path=/var/www/certbot \
        --domain "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email \
        $STAGING_FLAG

echo "✅ Certificate obtained for $DOMAIN"
echo "   cert: $CERTBOT_CONF/live/$DOMAIN/fullchain.pem"
echo ""
echo "Next: docker compose -f docker-compose.prod.yml --env-file .env.prod up -d"
