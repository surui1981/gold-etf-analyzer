"""V0.73.x+ 修复：MarketDataRepository 改为进程级单例。

**问题背景**：
原 ``get_market_data_repository`` 是 FastAPI ``Depends`` 默认 request-scoped
依赖函数，每次请求都新建 ``MarketDataRepository``，导致进程级状态
``_sources / _fetched_at / _last_date`` 被立即丢弃，
``/api/v1/market/health`` 永远返回 ``{"sources":{}}``。

**修复**：
改用 ``functools.lru_cache`` 进程级单例（保持外层 ``get_market_data_repository``
以便 ``app.dependency_overrides`` 仍能整体替换）。
"""

from __future__ import annotations


def test_get_market_data_repository_is_singleton() -> None:
    """同一进程内多次调用必须返回同一实例（共享 _sources 状态）。"""
    from app.dependencies import get_market_data_repository

    repo_a = get_market_data_repository()
    repo_b = get_market_data_repository()
    assert repo_a is repo_b, "get_market_data_repository 必须返回同一实例，否则 _sources 状态被丢弃"


def test_singleton_preserves_sources_across_calls() -> None:
    """_mark() 写进的状态对后续调用必须可见（_sources 非空）。"""
    from app.dependencies import get_market_data_repository

    repo = get_market_data_repository()
    repo._sources.clear()
    repo._mark("silver_etf", True)
    repo._mark("silver_ny", True)

    # 重新获取（应得到同一实例）
    repo2 = get_market_data_repository()
    assert repo2 is repo
    assert "silver_etf" in repo2._sources, "_mark 写入的 silver_etf 必须可见"
    assert "silver_ny" in repo2._sources
    assert repo2._sources["silver_etf"] == "live"


def test_singleton_independent_from_dependency_overrides() -> None:
    """测试可通过 app.dependency_overrides 整体替换（不影响单例本身）。

    此处只断言单例返回的是真实仓储实例；替换能力由 FastAPI 依赖覆盖机制保证
    （``app.dependency_overrides[get_market_data_repository]``）。
    """
    from app.dependencies import get_market_data_repository
    from app.repositories.market_data import MarketDataRepository

    repo = get_market_data_repository()
    assert isinstance(repo, MarketDataRepository)
