"""交易面服务：开仓、加/减仓、清仓、持仓估值与盈亏计算。"""

from decimal import Decimal

from app.repositories.market_data import DEFAULT_GOLD_ETF_NAME, MarketDataRepository
from app.repositories.position import PositionRepository, utcnow
from app.schemas.position import (
    PositionCreate,
    PositionDeleteOut,
    PositionOut,
    PositionSummary,
    TradeRecordOut,
    TradeRequest,
)
from app.utils.grams import shares_from_grams
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PositionService:
    """个人交易跟踪：持仓生命周期管理与实时盈亏。

    V0.62.0（P1 #6）起支持**单用户多账本**：所有方法接受可选 ``account_id``，
    ``None`` 表示全部账本（合并视图）；开仓时未指定账本则落到默认账本。
    """

    def __init__(
        self,
        repo: PositionRepository,
        market: MarketDataRepository,
        accounts: object | None = None,
    ) -> None:
        self._repo = repo
        self._market = market
        # 账本服务（可选注入：单测可省略，此时退化为单账本 id=1）
        self._accounts = accounts

    async def _resolve_account(self, account_id: int | None) -> int:
        """解析开仓账本：指定则校验，未指定则取默认账本。"""
        if self._accounts is None:
            return account_id if account_id is not None else 1
        return await self._accounts.resolve(account_id)  # type: ignore[attr-defined]

    async def open(self, request: PositionCreate, account_id: int | None = None) -> PositionOut:
        """开仓：创建持仓 + 买入流水。

        V0.70.0（P2 #8）支持按克开仓：当 ``request.grams`` 有值时按当前克价折算
        份数（向下取整到 100 份一手），同时把克数写入 ``grams_held`` 列。
        grams 与 quantity **互斥**（Schema 已前置校验，二次校验在此保护）。
        """
        grams = request.grams
        quantity = request.quantity
        if (grams is None) == (quantity is None):
            raise ValueError("quantity 与 grams 必须二选一")

        target_account = await self._resolve_account(account_id)
        grams_held: float | None = None

        if grams is not None:
            etf_px = await self._etf_price()
            gram_px = await self._gram_price()
            quantity = shares_from_grams(grams, etf_px, gram_px)
            grams_held = round(float(Decimal(str(grams))), 3)

        position = await self._repo.create_position(
            symbol=request.symbol,
            name=DEFAULT_GOLD_ETF_NAME,
            quantity=quantity,  # type: ignore[arg-type]
            avg_cost=request.price,
            account_id=target_account,
            grams_held=grams_held,
        )
        await self._repo.add_trade(
            position_id=position.id,
            side="buy",
            quantity=quantity,  # type: ignore[arg-type]
            price=request.price,
            fee=request.fee,
        )
        logger.info(
            "Position opened: id=%s account=%s qty=%s grams=%s @ %s",
            position.id,
            target_account,
            quantity,
            grams_held,
            request.price,
        )
        return await self._to_out(position)

    async def add_trade(self, position_id: int, request: TradeRequest) -> PositionOut:
        """加仓（buy）或减仓（sell），均价法摊薄成本。

        V0.70.0（P2 #8）支持按克加减仓：``request.grams`` 有值时按当前克价折算
        份数；买入累加 grams_held；卖出按「金额比例」扣减（与 quantity 同步）；
        超额扣减抛 ``ValueError``（HTTP 400）。
        """
        position = await self._repo.get(position_id)
        if position is None or position.status != "open":
            raise ValueError("持仓不存在或已平仓")

        grams = request.grams
        quantity = request.quantity
        if (grams is None) == (quantity is None):
            raise ValueError("quantity 与 grams 必须二选一")

        grams_held_delta: float | None = None
        if grams is not None:
            etf_px = await self._etf_price()
            gram_px = await self._gram_price()
            quantity = shares_from_grams(grams, etf_px, gram_px)
            grams_held_delta = round(float(Decimal(str(grams))), 3)
            # 卖出且按克时，先按克数校验（更贴近业务直觉；避免 quantity 校验先触发
            # 返回「份数」语义错信息，让用户看到的是克数不足）
            if request.side == "sell":
                base = float(position.grams_held) if position.grams_held is not None else 0.0
                if grams_held_delta > base:
                    raise ValueError(
                        f"减仓克数 {grams_held_delta:.3f} g 超过当前持有克数 {base:.3f} g"
                    )

        if request.side == "buy":
            total_cost = position.avg_cost * position.quantity + request.price * quantity  # type: ignore[operator]
            position.quantity += quantity  # type: ignore[operator]
            position.avg_cost = round(total_cost / position.quantity, 4)
            if grams_held_delta is not None:
                base = float(position.grams_held) if position.grams_held is not None else 0.0
                position.grams_held = round(base + grams_held_delta, 3)
        else:
            if quantity > position.quantity:  # type: ignore[operator]
                raise ValueError("减仓数量超过当前持仓")
            position.quantity -= quantity  # type: ignore[operator]  # 均价法：成本不变
            if grams_held_delta is not None:
                position.grams_held = (
                    round(float(position.grams_held) - grams_held_delta, 3)
                    if position.grams_held is not None
                    else None
                )
            if position.quantity == 0:
                position.status = "closed"
                position.closed_at = utcnow()

        await self._repo.save(position)
        await self._repo.add_trade(
            position_id=position_id,
            side=request.side,
            quantity=quantity,  # type: ignore[arg-type]
            price=request.price,
            fee=request.fee,
        )
        logger.info(
            "Trade %s on position %s: qty=%s grams_delta=%s @ %s, remaining=%s",
            request.side,
            position_id,
            quantity,
            grams_held_delta,
            request.price,
            position.quantity,
        )
        return await self._to_out(position)

    async def close(self, position_id: int) -> PositionOut:
        """清仓：按最新市价全部卖出。"""
        position = await self._repo.get(position_id)
        if position is None or position.status != "open":
            raise ValueError("持仓不存在或已平仓")
        if position.quantity <= 0:
            raise ValueError("持仓数量为空")

        market_price = await self._current_price()
        await self._repo.add_trade(
            position_id=position_id,
            side="sell",
            quantity=position.quantity,
            price=market_price,
        )
        position.quantity = 0.0
        position.grams_held = 0.0  # 清仓同步归零（V0.70.0 P2 #8）
        position.status = "closed"
        position.closed_at = utcnow()
        await self._repo.save(position)
        logger.info("Position closed: id=%s @ %s", position_id, market_price)
        return await self._to_out(position)

    async def delete(self, position_id: int) -> PositionDeleteOut:
        """软删除：标记删除而非物理删除，可随时撤销恢复。"""
        position = await self._repo.soft_delete(position_id)
        logger.info("Position soft-deleted: id=%s", position_id)
        return PositionDeleteOut(id=position.id, deleted=True, deleted_at=position.deleted_at)

    async def restore(self, position_id: int) -> PositionDeleteOut:
        """撤销软删除：恢复持仓显示。"""
        position = await self._repo.restore(position_id)
        logger.info("Position restored: id=%s", position_id)
        return PositionDeleteOut(id=position.id, deleted=False, deleted_at=position.deleted_at)

    async def list_positions(self, account_id: int | None = None) -> list[PositionOut]:
        """未平仓持仓（含实时估值）。

        Args:
            account_id: 账本过滤；None=全部账本
        """
        positions = await self._repo.list_open(account_id=account_id)
        return [await self._to_out(p) for p in positions]

    async def list_trades(self, position_id: int) -> list[TradeRecordOut]:
        """某持仓的完整成交流水（按时间倒序），用于复盘加仓/减仓过程。

        Args:
            position_id: 持仓 ID

        Returns:
            该持仓的成交流水列表（倒序）

        Raises:
            ValueError: 持仓不存在
        """
        position = await self._repo.get(position_id)
        if position is None:
            raise ValueError("持仓不存在")
        trades = await self._repo.list_trades(position_id)
        return [TradeRecordOut.model_validate(t) for t in trades]

    async def export_csv(self, account_id: int | None = None) -> str:
        """导出持仓与交易流水为 CSV 文本（供对账/备份）。

        Args:
            account_id: 账本过滤；None=全部账本
        """
        import csv
        import io

        positions = await self._repo.list_open(account_id=account_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# 持仓导出", "", "", "", "", "", "", "", "", "", "", ""])
        w.writerow(
            [
                "id",
                "symbol",
                "name",
                "quantity",
                "avg_cost",
                "grams_held",
                "status",
                "opened_at",
                "market_price",
                "market_value",
                "pnl",
                "pnl_pct",
            ]
        )
        for p in positions:
            out = await self._to_out(p)
            w.writerow(
                [
                    out.id,
                    out.symbol,
                    out.name,
                    out.quantity,
                    out.avg_cost,
                    out.grams_held,
                    out.status,
                    out.opened_at,
                    out.market_price,
                    out.market_value,
                    out.pnl,
                    out.pnl_pct,
                ]
            )
        w.writerow([])
        w.writerow(["# 交易流水", "", "", "", "", "", ""])
        w.writerow(["id", "position_id", "side", "quantity", "price", "fee", "traded_at"])
        for p in positions:
            trades = await self._repo.list_trades(p.id)
            for t in trades:
                w.writerow([t.id, t.position_id, t.side, t.quantity, t.price, t.fee, t.traded_at])
        return buf.getvalue()

    async def summary(self, account_id: int | None = None) -> PositionSummary:
        """持仓摘要：未平仓持仓汇总（供决策引擎）。

        Args:
            account_id: 账本过滤；None=全部账本（合并口径）

        Note:
            V0.70.0（P2 #8）起，``PositionSummary.grams_held``（可选）携带
            汇总克数；当所有持仓均为「按份」时为 None（避免对历史数据臆测）。
        """
        positions = await self._repo.list_open(account_id=account_id)
        if not positions:
            return PositionSummary()

        total_qty = sum(p.quantity for p in positions)
        total_cost = sum(p.avg_cost * p.quantity for p in positions)
        weighted_cost = total_cost / total_qty if total_qty else 0.0
        market_price = await self._current_price()
        pnl = (market_price - weighted_cost) * total_qty
        pnl_pct = (market_price - weighted_cost) / weighted_cost * 100 if weighted_cost else 0.0

        return PositionSummary(
            has_position=True,
            quantity=round(total_qty, 2),
            avg_cost=round(weighted_cost, 4),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            position_ratio=0.0,  # 账户本金未知，暂不估算
        )

    async def _current_price(self) -> float:
        """518880 黄金ETF 最新价（人民币元/份）——持仓估值专用。

        V0.61.0 修正：此前误用 ``get_gold_quote()``（返回 XAU/USD 国际金价，
        美元/盎司，约 4349），与人民币 ETF 成本（约 9 元/份）量纲不一致，
        导致浮动盈亏与收益率虚高数万个百分点。现改用 ``get_gold_etf_quote()``，
        价格口径与收益曲线同源。
        """
        quote = await self._market.get_gold_etf_quote()
        return quote.price_usd

    async def _etf_price(self) -> Decimal:
        """ETF 最新价（Decimal）——「按克开仓」折算专用。"""
        return Decimal(str(await self._current_price()))

    async def _gram_price(self) -> Decimal:
        """克价（元/克，Decimal）——「按克开仓」折算专用。

        取 ``MarketDataRepository.get_gold_gram_quote``（上海金 Au99.99），
        数据源异常时返回 ``Decimal('0')``（让 ``shares_from_grams`` 抛
        ValueError，转化为 HTTP 400）。
        """
        try:
            quote = await self._market.get_gold_gram_quote()
        except Exception as exc:
            logger.warning("gram quote fetch failed: %s", exc)
            return Decimal("0")
        px = getattr(quote, "price_usd", None)
        if not px:
            return Decimal("0")
        return Decimal(str(px))

    async def _to_out(self, position: object) -> PositionOut:
        """ORM → 输出模型，并补充实时估值。"""
        out = PositionOut.model_validate(position)
        # grams_held 在 Numeric 列上会被 Pydantic 序列化为 float；保持兼容
        out.grams_held = (
            float(position.grams_held) if position.grams_held is not None else None
        )
        market_price = await self._current_price()
        out.market_price = market_price
        out.market_value = round(position.quantity * market_price, 2)
        out.pnl = round((market_price - position.avg_cost) * position.quantity, 2)
        out.pnl_pct = (
            round((market_price - position.avg_cost) / position.avg_cost * 100, 2)
            if position.avg_cost
            else 0.0
        )
        return out
