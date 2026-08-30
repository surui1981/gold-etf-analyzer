"""行情数据源抽象：定义统一接口，后续可无痛切换真实数据源。"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GoldQuote:
    """黄金现货报价（数据源无关的返回值）。"""

    symbol: str
    price_usd: float
    change_pct: float
    updated_at: datetime


class MarketDataRepository:
    """行情数据源抽象接口。

    当前为内置 Mock 实现（骨架期演示用）。
    后续接入真实行情源（腾讯自选股 / 交易所 API / 自建采集服务）时，
    只需保持 ``get_gold_quote`` 签名不变，替换内部实现即可。
    """

    async def get_gold_quote(self, symbol: str = "XAU") -> GoldQuote:
        """获取黄金现货报价。

        Args:
            symbol: 合约/品种代码，默认 XAU（伦敦金）

        Returns:
            GoldQuote 报价对象

        TODO: 接入真实行情源后移除 Mock 逻辑。
        """
        return GoldQuote(
            symbol=symbol,
            price_usd=2350.5,
            change_pct=0.42,
            updated_at=datetime.now(timezone.utc),
        )
