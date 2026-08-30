"""应用配置：基于 pydantic-settings，环境变量优先，自动读取项目根 .env。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：src/app/config.py -> parents[3] = 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[3]


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

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 CORS 来源为列表，* 表示放行全部。"""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return ["*"] if "*" in origins else origins


@lru_cache
def get_settings() -> Settings:
    """返回缓存的配置单例，避免重复解析 .env。"""
    return Settings()
