"""克数 ↔ 份数 换算工具测试（V0.88.0 维护线覆盖率扩充）。

目标覆盖率：utils/grams.py 56% → **100%**（7 个分支全打到）。

被测函数：
- ``shares_from_grams``：克数 → 整手份数（100 份为一手，ROUND_FLOOR）
- ``grams_from_shares``：份数 → 克数（3 位小数精度）
- ``LOT_SIZE = 100`` 常量（验证约定）

设计要点：
- 项目里金额计算一律用 ``Decimal``（避免浮点累积误差）；入参允许
  ``Decimal | float | int``，函数内部 ``Decimal(str(x))`` 强制字符串化。
- 测试用 ``pytest.param`` + ``Decimal`` 标记参数化，覆盖三类型入参。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.utils.grams import LOT_SIZE, grams_from_shares, shares_from_grams

# ──────────────── shares_from_grams ────────────────


class TestSharesFromGrams:
    """``shares_from_grams`` 正常路径 + 4 类异常 + 类型矩阵。"""

    def test_normal_round_to_lot(self) -> None:
        """正常折算：1000g × 1.0 元/g ÷ 1.0 元/份 = 1000 份 = 10 手。"""
        result = shares_from_grams(grams=1000, etf_px=1.0, gram_px=1.0)
        assert result == 1000
        assert result % LOT_SIZE == 0, "结果必须是整手"

    def test_normal_floor_partial_lot_dropped(self) -> None:
        """折算后非整手：向下取整到 100 倍数（partial lot 丢弃）。

        999g × 1.0 元/g ÷ 1.0 元/份 = 999 份 = 9 手（900 份）→ 余 99 份丢弃。
        """
        result = shares_from_grams(grams=999, etf_px=1.0, gram_px=1.0)
        assert result == 900

    def test_below_lot_raises_with_min_grams_hint(self) -> None:
        """不足 1 手：抛 ValueError 且错误信息含「至少 X g」提示。

        1g × 1.0 ÷ 1.0 = 1 份（< 100 份一手）→ 触发。
        """
        with pytest.raises(ValueError, match="不足一手"):
            shares_from_grams(grams=1, etf_px=1.0, gram_px=1.0)

    def test_zero_grams_raises(self) -> None:
        """grams == 0：抛 ValueError 含「grams 必须 > 0」。"""
        with pytest.raises(ValueError, match="grams 必须 > 0"):
            shares_from_grams(grams=0, etf_px=1.0, gram_px=1.0)

    def test_negative_grams_raises(self) -> None:
        """grams < 0：抛 ValueError（与 0 同分支）。"""
        with pytest.raises(ValueError, match="grams 必须 > 0"):
            shares_from_grams(grams=-100, etf_px=1.0, gram_px=1.0)

    def test_zero_etf_px_raises(self) -> None:
        """etf_px == 0：抛 ValueError（防「0 价 → 0 份」静默吞错）。"""
        with pytest.raises(ValueError, match="etf_px 必须 > 0"):
            shares_from_grams(grams=1000, etf_px=0, gram_px=1.0)

    def test_zero_gram_px_raises(self) -> None:
        """gram_px == 0：抛 ValueError（防除零）。"""
        with pytest.raises(ValueError, match="gram_px 必须 > 0"):
            shares_from_grams(grams=1000, etf_px=1.0, gram_px=0)

    @pytest.mark.parametrize(
        "grams,etf_px,gram_px",
        [
            (1000, 1.0, 1.0),  # 全 float
            (Decimal("1000"), Decimal("1.0"), Decimal("1.0")),  # 全 Decimal
            (1000, 1.0, Decimal("1.0")),  # 混合 int + float + Decimal
        ],
        ids=["float", "decimal", "mixed"],
    )
    def test_accepts_mixed_types(self, grams, etf_px, gram_px) -> None:
        """入参类型：Decimal / float / int / 混合 都接收（强制 Decimal(str(x))）。"""
        result = shares_from_grams(grams=grams, etf_px=etf_px, gram_px=gram_px)
        assert isinstance(result, int)
        assert result > 0


# ──────────────── grams_from_shares ────────────────


class TestGramsFromShares:
    """``grams_from_shares`` 正常路径 + 4 类异常 + 边界（0 shares）。"""

    def test_normal_roundtrip_3dp(self) -> None:
        """shares → grams 3 位精度保留。

        1000 份 × 5.0 元/份 ÷ 1.0 元/g = 5000.000 g。
        """
        result = grams_from_shares(shares=1000, etf_px=5.0, gram_px=1.0)
        assert result == Decimal("5000.000")

    def test_shares_zero_returns_zero(self) -> None:
        """shares == 0：边界（docstring 允许 ≥0）→ 返回 Decimal("0.000")。"""
        result = grams_from_shares(shares=0, etf_px=5.0, gram_px=1.0)
        assert result == Decimal("0.000")

    def test_negative_shares_raises(self) -> None:
        """shares < 0：抛 ValueError（与 grams_from 边界略不同，grams 不允许 0）。"""
        with pytest.raises(ValueError, match="shares 不能为负"):
            grams_from_shares(shares=-100, etf_px=5.0, gram_px=1.0)

    def test_zero_etf_px_raises(self) -> None:
        """etf_px == 0：抛 ValueError（与 shares_from 同语义）。"""
        with pytest.raises(ValueError, match="etf_px 必须 > 0"):
            grams_from_shares(shares=1000, etf_px=0, gram_px=1.0)

    def test_zero_gram_px_raises(self) -> None:
        """gram_px == 0：抛 ValueError（防除零）。"""
        with pytest.raises(ValueError, match="gram_px 必须 > 0"):
            grams_from_shares(shares=1000, etf_px=5.0, gram_px=0)


# ──────────────── 常量 ────────────────


def test_lot_size_constant() -> None:
    """``LOT_SIZE = 100`` 是项目约定（ETF 100 份为一手）；任何修改需明确评估。"""
    assert LOT_SIZE == 100


# ──────────────── 往返一致性 ────────────────


class TestRoundtrip:
    """``shares_from_grams`` ⇄ ``grams_from_shares`` 往返保留整数倍。"""

    def test_int_lot_grams_back_to_same_shares(self) -> None:
        """整手克数 → shares → grams → shares：应保持原 shares。

        已知 g=1000 → shares=1000 (LOT_SIZE 倍) → grams=1000.000 → shares=1000。
        """
        original_shares = shares_from_grams(grams=1000, etf_px=1.0, gram_px=1.0)
        grams = grams_from_shares(shares=original_shares, etf_px=1.0, gram_px=1.0)
        roundtrip_shares = shares_from_grams(grams=grams, etf_px=1.0, gram_px=1.0)
        assert roundtrip_shares == original_shares
