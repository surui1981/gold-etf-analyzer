# 快速开始与配置

> 本指南已拆分为 5 部分，本文件包含 **快速开始（§4）+ 配置说明（§8）**。
> 其他部分：[overview](overview.md) · [architecture](architecture.md) ·
> [api-reference](api-reference.md) · [development](development.md)
>
> 完整索引见 [application-guide.md](application-guide.md)。

## 4. 快速开始

```bash
# 1) 安装依赖（uv 或 pip）
python -m pip install -e ".[dev]"

# 2) 启动服务（默认 127.0.0.1:8888）
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# 3) 浏览器访问
#    趋势页：  http://127.0.0.1:8888/
#    API 文档：http://127.0.0.1:8888/docs
```

**测试与代码质量**

```bash
python -m pytest -v          # 867 用例（离线回归 823 passed，排除 2 个联网 fetcher 文件 44 用例）：服务层 + API 集成 + scheduler / cache / intraday / help / providers / 业绩分析 / 多账本 / 多时间框架 / 消息面槽位 / 研判复盘 / 共振信号 / 克数持仓 / 白银 / 回测 / i18n / 埋点 / push / 仪表盘布局 / 认证（V0.75.0）
ruff check src tests          # 静态检查
ruff format src tests         # 格式化
```

**Docker 部署**

```bash
docker compose up --build     # 同样映射 127.0.0.1:8888
```

---

## 8. 配置说明（.env）

```ini
APP_NAME=gold-etf-analyzer
APP_ENV=dev            # dev/prod/test
DEBUG=true             # 开发期打印 SQL
DATABASE_URL=sqlite+aiosqlite:///./data/gold_etf.db
CORS_ORIGINS=*         # 逗号分隔，* 表示全部放行（仅开发）

# ===== V0.75.0 · 认证骨架（多用户登录）=====
AUTH_ENABLED=false              # 总开关；false = 单用户模式（与 V0.74.3 行为一致）
ALLOW_REGISTRATION=true         # 是否开放注册（首个用户始终可注册，自动 owner）
SESSION_TTL_HOURS=336           # 会话有效期（14 天）
SESSION_COOKIE_NAME=pm_session
SESSION_COOKIE_SECURE=false     # 生产（HTTPS）必须置 true
CSRF_COOKIE_NAME=pm_csrf
BCRYPT_COST=12                  # 测试可降到 4 提速
LOGIN_MAX_ATTEMPTS=5            # 滑动窗口内最大失败次数
LOGIN_ATTEMPT_WINDOW_MINUTES=15
LOGIN_LOCKOUT_MINUTES=15
SESSION_TOUCH_SECONDS=300       # last_seen_at 最小写间隔
TRUST_PROXY_HEADERS=false       # 反代后取 X-Forwarded-For 作为真实 IP
```

> `.env` 不入库（.gitignore）；`data/`、`*.db` 同样排除。
> 生产环境请改用 `.env.prod.example` 的取值：`AUTH_ENABLED=true` + `SESSION_COOKIE_SECURE=true` + `TRUST_PROXY_HEADERS=true`。

---