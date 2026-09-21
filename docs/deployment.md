# 部署 Runbook（V0.72.0 P3-b）

> 本文档是 **生产环境** 部署指南，覆盖 Docker 多阶段 + Nginx 反代 + Let's Encrypt
> HTTPS + 备份自动化。dev 模式（`127.0.0.1:8888`）开发期使用，**不需**本 runbook。

## 1. 前置要求

- **服务器**：1 vCPU / 1 GB RAM / 20 GB SSD 即可（SQLite + 单进程 FastAPI）。
- **操作系统**：Ubuntu 22.04 LTS / Debian 12（与 docker-compose 镜像兼容性最好）。
- **域名**：已购买 + A 记录指向服务器公网 IP（Let's Encrypt 验证需要）。
- **Docker**：20.10+ + Compose v2。
- **公网 80/443 端口**：Nginx + Certbot 占用；App 仅暴露在 Docker 内部网络（expose 而非 publish）。

```bash
# Ubuntu 安装 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# 重新登录以生效 group
```

## 2. 克隆代码

```bash
git clone https://github.com/surui1981/gold-etf-analyzer.git
cd gold-etf-analyzer
git checkout v0.72.0   # 或 main（生产建议固定 tag）
```

## 3. 编辑 `.env.prod`

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod          # 仅 root 可读
$EDITOR .env.prod
```

**必填项**：

- `ADMIN_TOKEN`：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `CORS_ORIGINS`：`https://your-domain.com`（不要带尾斜杠）
- `SMTP_*` / `SERVERCHAN_SENDKEY`：可选；留空 = 禁用对应渠道

## 4. 初始化 HTTPS 证书

首次部署用 `deploy/init-letsencrypt.sh`（webroot 挑战）：

```bash
# 临时把 80 端口让给 certbot —— 脚本会先 dry-run，确认无误再正式签发
sudo ./deploy/init-letsencrypt.sh \
    --domain gold.example.com \
    --email admin@example.com
```

脚本会做：

1. **dry-run**：验证域名 + 邮箱 + 服务器连通性。
2. **正式签发**：调用 `certbot certonly --webroot`，证书存到 `certbot/conf/`。
3. **设置自动续期**：写 cron（`certbot renew --quiet`）每日 03:00 跑。

## 5. 启动所有服务

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

服务清单（5 个）：

| 服务 | 镜像 | 端口 | 用途 |
|---|---|---|---|
| `app` | `gold-etf-analyzer:v0.72.0` | 内部 8888 | FastAPI |
| `nginx` | `nginx:1.27-alpine` | 80 / 443 | 反代 + 静态资产直出 |
| `certbot` | `certbot/certbot` | - | 证书自动续期 |
| `backup` | `gold-etf-analyzer:v0.72.0` | - | SQLite 每日 .backup |
|（healthcheck）| - | - | `app` 启动后 `nginx` 才会起（depends_on condition: service_healthy） |

## 6. 验证

```bash
# 1. 健康检查
curl -fsS http://localhost/api/v1/health
# 期望：{"status":"ok","app":"gold-etf-analyzer","env":"prod",...}

# 2. HTTPS 头
curl -I https://gold.example.com
# 期望：HTTP/2 200；HSTS / X-Frame-Options / X-Content-Type-Options 头齐全

# 3. 写端点守卫
curl -X POST -i https://gold.example.com/api/v1/positions \
    -H "Content-Type: application/json" \
    -d '{}'
# 期望：401 Unauthorized，body 含 "admin token required"

# 4. 带 token 写
curl -X POST -i https://gold.example.com/api/v1/positions \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}'
# 期望：400 / 201（schema 校验）

# 5. 限速
for i in {1..130}; do
    curl -s -o /dev/null -w "%{http_code}\n" https://gold.example.com/api/v1/health
done | tail -5
# 期望：前 120 个 200，后面开始 429 + Retry-After: 60

# 6. 证书过期时间
echo | openssl s_client -connect gold.example.com:443 2>/dev/null | openssl x509 -noout -dates
# 期望：notAfter 距今 ≥60 天（首次签发 90 天，每天 cron 续期到 ≥60）

# 7. 备份文件
ls -la backups/
# 期望：gold_etf-YYYY-MM-DD.db 每日一个
```

## 7. 监控 & 维护

### 日志

```bash
# 单服务实时日志
docker compose -f docker-compose.prod.yml logs -f app

# 全部服务
docker compose -f docker-compose.prod.yml logs -f

# 限速 500 行
docker compose -f docker-compose.prod.yml logs --tail 500 app
```

### 备份恢复

```bash
# 列出备份
ls backups/ | sort

# 恢复（先停 app）
docker compose -f docker-compose.prod.yml stop app
sqlite3 data/gold_etf.db ".restore backups/gold_etf-2026-09-21.db"
docker compose -f docker-compose.prod.yml start app
```

### 升级

```bash
git pull
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d app
```

> ⚠️ **数据库迁移**：V0.71.0+ 已在 `main.lifespan` 启动时自动跑 `alembic upgrade head`，
> 无需手动执行。如迁移失败，App 会回退到 `create_all`（仅创建缺失表，不修改 schema）。

### 回滚

```bash
# 回滚到上一版本
docker compose -f docker-compose.prod.yml down
git checkout v0.71.0
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d
```

> 数据库结构不向下兼容时（如 drop column），需手动 `alembic downgrade -1`。

## 8. 故障排查

| 现象 | 排查 |
|---|---|
| App 启动报 `ModuleNotFoundError: aiosmtplib` | 多阶段 build 没成功；`docker compose build --no-cache app` |
| 502 Bad Gateway | `app` 还没起；等 40s（`start_period`）后重试 |
| 403 Forbidden on `/` | CORS 域名不匹配；检查 `CORS_ORIGINS` |
| 证书续期失败 | `docker compose logs certbot`；常见原因：80 端口被占 |
| 备份失败 | `docker compose logs backup`；常见原因：磁盘满 |
| 持续 429 | `RATE_LIMIT_PER_MIN=240` 调高；监控 `server.log` 找高频 IP |
| 推送无响应 | 检查 `SMTP_*` 凭据；QQ 邮箱用授权码不是登录密码；`SERVERCHAN_SENDKEY` 失效需重新申请 |

## 9. 安全清单

部署前确认：

- [ ] `.env.prod` 权限 `600`，仅 root 可读
- [ ] `ADMIN_TOKEN` ≥32 字符（`secrets.token_urlsafe(32)`）
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` 用具体域名，不用 `*`
- [ ] 服务器防火墙（ufw）只开 22 / 80 / 443
- [ ] SSH 改用 key 登录，禁用密码
- [ ] 自动安全更新启用：`unattended-upgrades`
- [ ] 备份目录 `backups/` 不在 git 仓库，定期异地拷贝

## 10. 进阶：Caddy 替代 Nginx

若运维偏好 Caddy（自动 HTTPS、无需 certbot），`deploy/Caddyfile` 是 starter：

```caddyfile
gold.example.com {
    encode zstd gzip
    reverse_proxy app:8888
    handle /static/* {
        root * /usr/share/caddy/static
        file_server
    }
}
```

Caddy 镜像仅 1 个容器，比 nginx + certbot 简洁，但运维生态不如 nginx 普及。
