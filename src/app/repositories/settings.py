"""应用配置仓储：key-value 数据访问。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting


class SettingRepository:
    """通用配置存取。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        """读取配置值；不存在返回 None。"""
        stmt = select(AppSetting).where(AppSetting.key == key)
        setting = (await self._session.execute(stmt)).scalar_one_or_none()
        return setting.value if setting else None

    async def set(self, key: str, value: str) -> None:
        """写入/更新配置值。"""
        stmt = select(AppSetting).where(AppSetting.key == key)
        setting = (await self._session.execute(stmt)).scalar_one_or_none()
        if setting is None:
            self._session.add(AppSetting(key=key, value=value))
        else:
            setting.value = value
        await self._session.commit()
