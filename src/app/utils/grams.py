"""克数 ↔ 份数 换算工具（V0.70.0 P2 #8）。

业务背景：实物金 / 积存金 业务天然按「克」计价（人民币元/克），但二级市场 ETF
（518880 等）按「份」计价（人民币元/份，100 份为一手）。两端通过「克价」折算：

    value_cny = grams × gram_px
    shares    = floor(value_cny / etf_px / 100) × 100

约定：
- 入参 / 出参一律使用 ``Decimal``，避免浮点累积误差（金额计算禁用 float）；
- 任何舍入导致 ``shares == 0`` 抛 ``ValueError``（服务层转 HTTP 400，提示用户
  克数太少）；反向换算不做舍入。
- 任一价格 ≤ 0 即视为数据源异常，抛 ``ValueError``（防「0 价 → 0 份」静默吞错）。
"""

from decimal import ROUND_FLOOR, Decimal

LOT_SIZE = 100  # ETF 100 份为一手（最小交易单位）


def shares_from_grams(
    grams: Decimal | float | int,
    etf_px: Decimal | float | int,
    gram_px: Decimal | float | int,
) -> int:
    """克数 → 份数（向下取整到 100 份一手）。

    Args:
        grams: 克数（>0）
        etf_px: ETF 最新价（元/份，>0）
        gram_px: 克价（元/克，>0）

    Returns:
        整手份数（100 的倍数）

    Raises:
        ValueError: grams ≤ 0 / 任一价格 ≤ 0 / 折算不足一手
    """
    g = Decimal(str(grams))
    e = Decimal(str(etf_px))
    p = Decimal(str(gram_px))

    if g <= 0:
        raise ValueError(f"grams 必须 > 0，当前 {g}")
    if e <= 0:
        raise ValueError(f"etf_px 必须 > 0，当前 {e}")
    if p <= 0:
        raise ValueError(f"gram_px 必须 > 0，当前 {p}")

    value_cny = g * p
    raw_shares = value_cny / e
    lots = (raw_shares / LOT_SIZE).to_integral_value(rounding=ROUND_FLOOR)
    shares = int(lots) * LOT_SIZE

    if shares <= 0:
        # 折算后不足一手；提示「至少多少克才够一手」
        min_grams = (e * LOT_SIZE / p).quantize(Decimal("0.001"))
        raise ValueError(f"克数 {g} g 折算后不足一手（{LOT_SIZE} 份）；至少 {min_grams} g")
    return shares


def grams_from_shares(
    shares: int | float,
    etf_px: Decimal | float | int,
    gram_px: Decimal | float | int,
) -> Decimal:
    """份数 → 克数（按当前克价还原，不做舍入）。

    Args:
        shares: 份数（≥0）
        etf_px: ETF 最新价（元/份，>0）
        gram_px: 克价（元/克，>0）

    Returns:
        克数（Decimal，3 位小数精度）

    Raises:
        ValueError: shares < 0 / 任一价格 ≤ 0
    """
    s = Decimal(str(shares))
    e = Decimal(str(etf_px))
    p = Decimal(str(gram_px))

    if s < 0:
        raise ValueError(f"shares 不能为负，当前 {s}")
    if e <= 0:
        raise ValueError(f"etf_px 必须 > 0，当前 {e}")
    if p <= 0:
        raise ValueError(f"gram_px 必须 > 0，当前 {p}")

    value_cny = s * e
    grams = value_cny / p
    return grams.quantize(Decimal("0.001"))


__all__ = ["LOT_SIZE", "grams_from_shares", "shares_from_grams"]
