"""应用配置：基于 pydantic-settings，环境变量优先，自动读取项目根 .env。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：src/app/config.py -> parents[2] = 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置。

    环境变量（如 DATABASE_URL）优先级高于 .env 文件；
    未配置时使用下方默认值。
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "gold-etf-analyzer"
    app_env: str = "dev"
    debug: bool = False

    # SQLite 默认存到 data/ 目录（启动时自动创建）
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'gold_etf.db'}"

    # CORS 来源，逗号分隔；* 表示全部放行（仅限本地开发）
    cors_origins: str = "*"

    # ===== 行情源（V0.59.0 新增，P1 #5 行情源配置化）=====
    # 数据源 provider：akshare | mock | eastmoney_only | sina_only
    market_provider: str = "akshare"

    # 数据源 URL（可被 .env 覆盖，方便企业内网代理 / 镜像）
    xau_live_api_url: str = "https://api.gold-api.com/price/XAU"
    sina_gc_url: str = "https://hq.sinajs.cn/list=hf_GC"
    h15_csv_url: str = (
        "https://www.federalreserve.gov/datadownload/Output.aspx"
        "?rel=H15&series=bf17364827e38702b42a58cf8eaa3f78&lastobs=&from=&to="
        "&filetype=csv&label=include&layout=seriescolumn"
    )

    # XAU 实时报价 fallback chain：逗号分隔，按顺序尝试
    # 可选 token：goldapi | sina | etf_history
    xau_fallback_chain: str = "goldapi,sina,etf_history"

    # V0.73.0 N+17：白银实时报价 fallback chain（NY SI 美元/盎司）
    # 可选 token：sina_si | yahoo_spot | history
    # - sina_si：新浪 hf_SI 实时（与 gold hf_GC 1:1 对称，零KEY、稳定）
    # - yahoo_spot：Yahoo Finance SI=F 最小请求 range=2d 拿当日 running bar
    # - history：复用 silver_history 历史 K 线最后一根（最终兜底）
    silver_fallback_chain: str = "sina_si,yahoo_spot"

    # 行情缓存 TTL（秒）；测试环境可设 0 禁用
    quote_cache_ttl: int = 300

    # 是否允许行情网络请求（false 时强制走 Mock，避免测试环境触网）
    network_enabled: bool = True

    # ===== 行情实时性（V0.60.0 新增）=====
    # Served cache 日内 TTL（秒）；超过此时间后下次请求会全量重算。
    # 默认 600（10 分钟），按"半日 A 股"量级；设置 0 表示仅依赖跨日 + invalidate_for_news 失效。
    served_cache_ttl_seconds: int = 600

    # 是否启用日内多次预热（默认启用）。
    # 设为 false 可回退到仅每日 07:00 BJT 一次的旧行为。
    intraday_refresh_enabled: bool = True

    # 日内预热触发时刻（北京时分，逗号分隔）。覆盖 A 股 + SGE 关键时点。
    # 默认：09:30 开盘前 / 11:30 上午收盘前 / 14:00 下午开盘前 / 15:30 SGE 收盘前。
    intraday_refresh_hours: str = "9:30,11:30,14:00,15:30"

    # ===== V0.72.0 P3-b · 安全前置 =====
    # 写端点 admin 守卫 token（X-Admin-Token 头）。None / 空 = dev 模式跳过校验。
    # 生产部署（.env.prod）必须设置一个 ≥32 字符随机串；建议用：
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    admin_token: str | None = None

    # 限速（per-IP 滑动窗口，60s）。0 = 禁用。
    # 默认 120 req/min（足够 9 页 SPA + 60s 轮询）；生产调高 240 应对异常峰值。
    rate_limit_per_min: int = 120

    # ===== V0.75.0 · 认证骨架（多用户登录）=====
    # 总开关。**默认 false = 单用户模式**：不解析会话、不校验 CSRF、
    # 所有请求以 LEGACY_USER_ID(1) 运行，行为与 V0.74.3 完全一致。
    # 设为 true 后才启用登录 / 注册 / 会话 cookie / CSRF 校验。
    auth_enabled: bool = False

    # 是否允许自助注册。单用户（私有部署）建议 false，只由 owner 建号；
    # 家庭 / 合伙场景设 true。无论取值如何，「库中无任何用户时」首个注册者
    # 一定被创建为 owner —— 否则会陷入「没人能建号」的死锁。
    allow_registration: bool = True

    # 会话有效期（小时）。默认 336 = 14 天；绝对过期，不随活跃度顺延
    # （顺延会让「长期不用的设备」永远在线）。
    session_ttl_hours: int = 336

    # 会话 cookie 名与安全属性。
    # secure=True 必须搭配 HTTPS；本地 http://127.0.0.1 下浏览器**不会回传**
    # Secure cookie，故 dev 默认 false，生产（.env.prod + nginx TLS）务必 true。
    session_cookie_name: str = "pm_session"
    session_cookie_secure: bool = False

    # CSRF double-submit cookie 名（非 HttpOnly，前端读取后回填 X-CSRF-Token 头）。
    csrf_cookie_name: str = "pm_csrf"

    # bcrypt 代价因子。12 ≈ 单次校验 250ms（现代 CPU），是「抗离线爆破」与
    # 「登录体感」的常用平衡点。调高会线性增加登录延迟。
    bcrypt_cost: int = 12

    # 登录失败锁定：同一「账号或 IP」在 window 内失败达到 max 次即锁定 lockout 分钟。
    # 防在线暴力破解；命中后即使密码正确也拒绝（返回同样的错误文案，不泄露状态）。
    login_max_attempts: int = 5
    login_attempt_window_minutes: int = 15
    login_lockout_minutes: int = 15

    # 会话 last_seen_at 落库节流（秒）：避免「每个 API 请求一次 UPDATE」。
    # 0 = 每次都写。
    session_touch_seconds: int = 300

    # 信任反向代理的 X-Forwarded-For 首跳作为客户端 IP（nginx / Cloudflare 前置时为真）。
    # ⚠ XFF 可伪造，仅用于「审计展示 + 登录节流」这类软用途，
    # 不用于任何安全判定（真正的限流由 rate_limit 中间件按连接 IP 做）。
    trust_proxy_headers: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS 来源为列表，* 表示放行全部。"""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return ["*"] if "*" in origins else origins

    @property
    def xau_fallback_chain_list(self) -> list[str]:
        """解析 XAU fallback chain 为 token 列表（已 trim + 过滤空）。"""
        return [t.strip() for t in self.xau_fallback_chain.split(",") if t.strip()]

    @property
    def silver_fallback_chain_list(self) -> list[str]:
        """解析白银 fallback chain 为 token 列表（已 trim + 过滤空）。"""
        return [t.strip() for t in self.silver_fallback_chain.split(",") if t.strip()]

    @property
    def intraday_refresh_hour_list(self) -> list[tuple[int, int]]:
        """解析日内预热触发时刻（"9:30,11:30,..."）为 [(hour, minute), ...] 元组列表。

        格式错误或空字符串会被静默跳过；调用方需自行处理空列表。
        """
        out: list[tuple[int, int]] = []
        for token in self.intraday_refresh_hours.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                hh_s, mm_s = token.split(":", 1)
                hh, mm = int(hh_s), int(mm_s)
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    out.append((hh, mm))
            except (ValueError, AttributeError):
                continue
        return out


@lru_cache
def get_settings() -> Settings:
    """返回缓存的配置单例，避免重复解析 .env。"""
    return Settings()
