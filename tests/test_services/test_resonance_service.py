"""共振信号服务单元测试（V0.70.0 P2 #7）。

覆盖：
- 4 类信号判定（strong_up / strong_down / weak_up / divergent / neutral）
- DIVERGENT 的三维背离判定与 subtype（V0.78.0：任意两维分差 ≥ 15）
- strength_up 命中统计（含样本不足警告）
- history 按日期倒序返回
- signal_today 的 target 透传（V0.75.1：黄金/白银复用同一口径）
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsScore
from app.schemas.resonance import DivergentSubtype
from app.services.resonance import ResonanceService, compute_resonance

# =========================================================================
# 纯函数 compute_resonance —— 4 类信号判定
# =========================================================================


def test_compute_strong_up_all_three_bullish() -> None:
    """三面同向看多（≥55）→ STRONG_UP。"""
    out = compute_resonance({"tech": 60, "macro": 62, "news": 58})
    assert out.signal == "strong_up"
    assert out.label == "强共振看多"
    assert 55 <= out.confidence <= 100
    assert out.components == {"tech": 60, "macro": 62, "news": 58}


def test_compute_strong_down_mirror() -> None:
    """三面同向看空（≤45）→ STRONG_DOWN。"""
    out = compute_resonance({"tech": 40, "macro": 38, "news": 42})
    assert out.signal == "strong_down"
    assert out.label == "强共振看空"


def test_compute_weak_up_two_of_three() -> None:
    """三面中 2 维看多 → WEAK_UP（confidence=65）。"""
    out = compute_resonance({"tech": 60, "macro": 48, "news": 58})
    assert out.signal == "weak_up"
    assert out.confidence == 65.0


def test_compute_divergent_mix() -> None:
    """tech 与 macro 反向（≥55 vs ≤45）→ DIVERGENT。"""
    out = compute_resonance({"tech": 65, "macro": 40, "news": 50})
    assert out.signal == "divergent"
    # confidence = (65 - 40) × 0.5 = 12.5
    assert out.confidence == pytest.approx(12.5, abs=0.1)


def test_compute_neutral_all_near_50() -> None:
    """三面都中性 → NEUTRAL（confidence=50）。"""
    out = compute_resonance({"tech": 50, "macro": 50, "news": 50})
    assert out.signal == "neutral"
    assert out.confidence == 50.0


def test_compute_score_date_propagates() -> None:
    """score_date 入参会出现在结果中。"""
    d = date(2026, 6, 1)
    out = compute_resonance({"tech": 60, "macro": 60, "news": 60}, score_date=d)
    assert out.score_date == d


def test_compute_default_dim_50_when_missing() -> None:
    """缺维度时按中性 50 兜底。"""
    out = compute_resonance({"tech": 60})  # macro / news 缺失
    # tech=60, macro=50, news=50 → tech 看多，宏观/消息中性 → 仅 1 维看多 → 中性或弱多
    assert out.signal in {"neutral", "weak_up"}


# =========================================================================
# ResonanceService —— 命中统计与历史回放
# =========================================================================


class FakeMarket:
    """假行情：返回单调上升 ETF 价格序列（用于构造「命中」样本）。"""

    def __init__(self, base_close: float = 10.0, daily_delta: float = 0.05) -> None:
        self.base_close = base_close
        self.daily_delta = daily_delta

    async def get_gold_history(self, days: int = 60):
        from datetime import timedelta

        from app.repositories.market_data import GoldKline

        start = date.today() - timedelta(days=days)
        return [
            GoldKline(
                date=start + timedelta(days=i),
                open=self.base_close,
                close=round(self.base_close + i * self.daily_delta, 4),
                high=self.base_close + 1,
                low=self.base_close - 1,
                volume=0.0,
            )
            for i in range(days)
        ]


class FakeNewsRepo:
    """假消息面仓储：内存中维护 NewsScore 列表，按日期查。"""

    def __init__(self, records: list[NewsScore]) -> None:
        self._records = records

    async def list_between(self, start: date, end: date) -> list[NewsScore]:
        return [r for r in self._records if start <= r.score_date <= end]


def _make_news(score_date: date, slot: int, score: float, notes: str = "") -> NewsScore:
    return NewsScore(
        score_date=score_date,
        slot=slot,
        score=score,
        direction="bullish" if score >= 55 else ("bearish" if score <= 45 else "neutral"),
        notes=notes,
        basis="",
        backfilled=0,
        scored_at=score_date,
    )


async def test_history_replays_trend_per_day(db_session: AsyncSession) -> None:
    """history(days)：5 个打分日 → 5 项按日期倒序。"""
    today = date.today()
    records = [_make_news(today - timedelta(days=i), 1, 60 + i) for i in range(5)]
    fake_news = FakeNewsRepo(records)
    service = ResonanceService.__new__(ResonanceService)  # 不调 __init__
    service._trend = None
    service._news = fake_news  # type: ignore[assignment]

    out = await service.history(days=10)
    assert out.total == 5
    # 按日期倒序
    dates = [it.score_date for it in out.items]
    assert dates == sorted(dates, reverse=True)
    # 每项至少含 score_date
    for it in out.items:
        assert it.score_date is not None


async def test_strength_up_filters_bullish_news_only() -> None:
    """strength_up：仅当 effective_score ≥ 55 且 BULLISH 才计入。"""
    today = date.today()
    # 30 天 BULLISH（score=60）—— 在单调上升价序列里全部命中
    bull = [_make_news(today - timedelta(days=i), 1, 60) for i in range(30)]
    fake_news = FakeNewsRepo(bull)
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]

    fake_trend = SimpleNamespace(_repo=FakeMarket())
    service._trend = fake_trend  # type: ignore[assignment]

    out = await service.strength_up(days=30, horizon=1)
    # 30 天全部 BULLISH → total_strong_up=30；
    # 但 T+1 对今天/昨天尚未到期 → resolved=28（最近 2 天 pending）
    assert out.total_strong_up == 30
    assert out.resolved == 28
    assert out.hits == 28
    assert out.hit_rate == 100.0
    assert out.sample_warning is False


async def test_strength_up_sample_warning_below_threshold() -> None:
    """样本 < 20 → sample_warning=True。"""
    today = date.today()
    bull = [_make_news(today - timedelta(days=i), 1, 60) for i in range(15)]
    fake_news = FakeNewsRepo(bull)
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]
    service._trend = SimpleNamespace(_repo=FakeMarket())  # type: ignore[assignment]

    out = await service.strength_up(days=15, horizon=1)
    assert out.sample_warning is True
    assert "仅供参考" in out.note


async def test_strength_up_empty_window_returns_warning() -> None:
    """窗口无记录 → total=0 + warning。"""
    fake_news = FakeNewsRepo([])
    service = ResonanceService.__new__(ResonanceService)
    service._news = fake_news  # type: ignore[assignment]
    service._trend = SimpleNamespace(_repo=FakeMarket())  # type: ignore[assignment]

    out = await service.strength_up(days=30, horizon=1)
    assert out.total_strong_up == 0
    assert out.resolved == 0
    assert out.hit_rate is None
    assert out.sample_warning is True
    assert "无消息面打分记录" in out.note


# =========================================================================
# signal_today —— target 复用口径（V0.75.1）
# =========================================================================


class _RecordingTrend:
    """记录 analyze 收到的 target，供「口径透传」断言。"""

    def __init__(self, components: dict[str, float]) -> None:
        self._components = components
        self.calls: list[tuple[int, str]] = []

    async def analyze(self, days: int = 60, target: str = "etf"):
        self.calls.append((days, target))
        return SimpleNamespace(index=SimpleNamespace(components=self._components))


def _service_with_trend(trend: _RecordingTrend) -> ResonanceService:
    service = ResonanceService.__new__(ResonanceService)  # 不调 __init__
    service._trend = trend  # type: ignore[assignment]
    service._news = FakeNewsRepo([])  # type: ignore[assignment]
    return service


async def test_signal_today_defaults_to_etf_target() -> None:
    """不传 target → 仍走 etf（V0.70.0 行为，向后兼容）。"""
    trend = _RecordingTrend({"tech": 70, "macro": 65, "news": 60})
    service = _service_with_trend(trend)

    out = await service.signal_today()
    assert trend.calls == [(60, "etf")]
    assert out.signal == "strong_up"  # 三面 ≥55 → 强共振
    assert out.components == {"tech": 70, "macro": 65, "news": 60}


@pytest.mark.parametrize("target", ["ny", "gram", "silver_etf", "silver_ny", "silver_gram"])
async def test_signal_today_passes_target_through(target: str) -> None:
    """V0.75.1：target 原样透传到 TrendService.analyze。

    黄金/白银必须复用**同一套**三维一致性口径（阈值 55/45 + 标准差折扣），
    否则结论卡上的分歧提示会与共振卡口径不一致。
    """
    trend = _RecordingTrend({"tech": 50, "macro": 50, "news": 50})
    service = _service_with_trend(trend)

    out = await service.signal_today(target=target)
    assert trend.calls == [(60, target)]
    assert out.signal == "neutral"
    assert out.components == {"tech": 50, "macro": 50, "news": 50}


# =========================================================================
# DIVERGENT 背离判定（V0.78.0：任意两维分差 ≥ 15 + subtype）
# =========================================================================


def test_divergent_tech_vs_news_is_subtype_tech_news() -> None:
    """§3.5 核心场景：消息面看多 65、技术看空 35、宏观中性 50 → tech_news 背离。

    「消息面是客户对投行展望的主观判断，常领先于技术面」，这类反转先行信号
    在 V0.77.2 会被判 neutral（原实现只看 tech vs macro 方向），属整类遗漏。
    """
    out = compute_resonance({"tech": 35, "macro": 50, "news": 65})
    assert out.signal == "divergent"
    assert out.subtype == DivergentSubtype.TECH_NEWS
    assert out.subtype == "tech_news"  # StrEnum 与裸字符串相等，前端无需转换
    assert out.subtype_label == "技术面 vs 消息面"
    # confidence = (65 - 35) × 0.5 = 15.0（按最大幅度 30 算，不是 tech-macro 的 15）
    assert out.confidence == pytest.approx(15.0, abs=0.1)


def test_divergent_macro_vs_news_is_third_pair() -> None:
    """宏观 vs 消息面背离（V0.78.0 新增的第三对维度）。"""
    out = compute_resonance({"tech": 50, "macro": 30, "news": 70})
    assert out.signal == "divergent"
    assert out.subtype == DivergentSubtype.MACRO_NEWS
    assert out.subtype_label == "宏观面 vs 消息面"
    assert out.confidence == pytest.approx(20.0, abs=0.1)


def test_divergent_takes_largest_gap_not_first_hit() -> None:
    """三对都达标时取幅度最大的一对，而非 _DIVERGENT_PAIRS 中靠前者。

    复现用例 tech=35 / macro=50 / news=65：tech-macro 差 15（刚够阈值），
    tech-news 差 30。取首个会把显著背离误标成 tech_macro —— 这是实现时
    真实踩到的问题，故留断言锁死「取最大幅度」这一决策。
    """
    out = compute_resonance({"tech": 35, "macro": 50, "news": 65})
    assert out.subtype == DivergentSubtype.TECH_NEWS
    assert out.confidence == pytest.approx(15.0, abs=0.1)


def test_divergent_threshold_boundary_15_triggers() -> None:
    """幅度恰为 15 → 触发（判定用 >=）。"""
    out = compute_resonance({"tech": 50, "macro": 65, "news": 50})
    assert out.signal == "divergent"
    assert out.subtype == DivergentSubtype.TECH_MACRO


def test_divergent_threshold_boundary_14_does_not_trigger() -> None:
    """幅度 14 → 不触发，落到 neutral 且不携带 subtype。"""
    out = compute_resonance({"tech": 50, "macro": 64, "news": 50})
    assert out.signal == "neutral"
    assert out.subtype is None
    assert out.subtype_label == ""
    assert out.confidence == pytest.approx(50.0, abs=0.1)


def test_slight_opposite_directions_no_longer_divergent() -> None:
    """行为变更留档：56 vs 44 方向相反但幅度仅 12。

    V0.77.2 判 divergent（只看方向相反），V0.78.0 起判 neutral ——
    这是「取幅度 ≥ 15」这一**有意收紧**的直接后果：轻微分歧够不上
    结构性背离。写死在此以免被后人当回归改回。
    """
    out = compute_resonance({"tech": 56, "macro": 44, "news": 50})
    assert out.signal == "neutral"
    assert out.subtype is None


def test_divergent_subtype_serializes_as_plain_string() -> None:
    """subtype 必须以裸字符串进 JSON，否则前端查表 DIVERGENT_I18N 会落空。

    StrEnum 的两种形态不同：``model_dump()`` 给枚举对象、``model_dump_json()``
    才给字符串，而 FastAPI 的响应走后者。若将来 schema 调整（如加
    ``use_enum_values`` 或改回 ``str, Enum``）导致 JSON 里变成
    ``"DivergentSubtype.TECH_NEWS"``，前端会**静默**不显示背离类型 ——
    此断言即该静默失效的守卫。
    """
    out = compute_resonance({"tech": 35, "macro": 50, "news": 65})
    assert '"subtype":"tech_news"' in out.model_dump_json()
