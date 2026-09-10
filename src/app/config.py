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

    # 行情缓存 TTL（秒）；测试环境可设 0 禁用
    quote_cache_ttl: int = 300

    # 是否允许行情网络请求（false 时强制走 Mock，避免测试环境触网）
    network_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS 来源为列表，* 表示放行全部。"""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return ["*"] if "*" in origins else origins

    @property
    def xau_fallback_chain_list(self) -> list[str]:
        """解析 XAU fallback chain 为 token 列表（已 trim + 过滤空）。"""
        return [t.strip() for t in self.xau_fallback_chain.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存的配置单例，避免重复解析 .env。"""
    return Settings()
