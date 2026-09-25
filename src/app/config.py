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
