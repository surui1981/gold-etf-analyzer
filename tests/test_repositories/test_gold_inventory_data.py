"""COMEX 黄金库存 fetcher 单测：归一化容错 + 缓存 + 源不可用不 mock。"""

import asyncio
import dataclasses
import json
from datetime import date

import pytest

from app.repositories import gold_inventory_data as mod
from app.repositories.gold_inventory_data import (
    GoldInventorySourceError,
    InventoryPoint,
    _normalize_rows,
    fetch_comex_inventory,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清进程内缓存，避免用例间串。"""
    with mod._CACHE_LOCK:
        mod._CACHE.clear()
    yield
    with mod._CACHE_LOCK:
        mod._CACHE.clear()


# ──────────────── 归一化 ────────────────


def test_normalize_happy_path() -> None:
    """正常两行 → 按日期升序、字段落位。"""
    out = _normalize_rows(
        [
            {"date": "2026-10-20", "tonnes": 727.96, "ounces": 23404381.0},
            {"date": "2026-10-19", "tonnes": 728.63, "ounces": 23425905.0},
        ]
    )
    assert [p.inv_date for p in out] == [date(2026, 10, 19), date(2026, 10, 20)]
    assert [p.tonnes for p in out] == [728.63, 727.96]
    assert [p.ounces for p in out] == [23425905.0, 23404381.0]
    assert {p.source for p in out} == {"COMEX"}


def test_normalize_drops_bad_rows_individually() -> None:
    """坏行**逐行**丢弃，其余照常 —— 不是「一行坏就整批废」。

    这是本 fetcher 最重要的容错约定：源表多一行脏数据不该让整条库存线挂掉。

    分两类，处理方式不同：
    - **主字段（吨数）坏** → 整行丢：留着会让所有 ``change_pct`` 变 NaN，
      而 NaN 会一路渲染到用户面前（比空卡更坏）；
    - **副字段（盎司）坏** → 只置 None，行保留：盎司只是留档对账用的。
    """
    out = _normalize_rows(
        [
            {"date": "2026-01-02", "tonnes": 100.0, "ounces": 1.0},
            {"date": "not-a-date", "tonnes": 5.0, "ounces": 1.0},  # 日期坏 → 丢
            {"date": "2026-01-03", "tonnes": None, "ounces": 1.0},  # 吨数 None → 丢
            {"date": "2026-01-04", "tonnes": "abc", "ounces": 1.0},  # 吨数非数字 → 丢
            {"date": "2026-01-05", "tonnes": float("nan"), "ounces": 1.0},  # NaN → 丢
            {"date": "2026-01-06", "tonnes": float("inf"), "ounces": 1.0},  # inf → 丢
            {"date": "2026-01-07", "tonnes": 102.0, "ounces": "bad"},  # 盎司坏 → 留，置 None
            "junk",  # 非 dict → 丢
        ]
    )
    assert [p.inv_date for p in out] == [date(2026, 1, 2), date(2026, 1, 7)]
    assert out[-1].tonnes == 102.0
    assert out[-1].ounces is None


def test_normalize_dedups_same_day_keeps_last() -> None:
    """同一天重复出现 → 保留后写的那个。"""
    out = _normalize_rows(
        [
            {"date": "2026-01-02", "tonnes": 100.0, "ounces": 1.0},
            {"date": "2026-01-02", "tonnes": 200.0, "ounces": 2.0},
        ]
    )
    assert len(out) == 1
    assert out[0].tonnes == 200.0


def test_normalize_empty_returns_empty() -> None:
    assert _normalize_rows([]) == []


def test_normalize_all_bad_returns_empty() -> None:
    """全批皆废 → 空列表（由 fetch_comex_inventory 抛源错误，不静默返回空）。"""
    assert _normalize_rows([{"date": "x", "tonnes": 1.0}, {"date": "y", "tonnes": 1.0}]) == []


# ──────────────── fetch + 缓存 ────────────────


def test_fetch_uses_subprocess_and_caches(monkeypatch) -> None:
    """子进程结果被缓存：第二次不再起子进程。"""
    calls: list[int] = []

    def _fake_subprocess() -> list:
        calls.append(1)
        return [{"date": "2026-10-20", "tonnes": 727.96, "ounces": 23404381.0}]

    monkeypatch.setattr(mod, "_fetch_comex_via_subprocess", _fake_subprocess)

    first = fetch_comex_inventory()
    second = fetch_comex_inventory()
    assert len(calls) == 1, "第二次命中缓存，不该再起子进程"
    assert first == second
    assert first[0].inv_date == date(2026, 10, 20)


def test_fetch_bypasses_cache_when_asked(monkeypatch) -> None:
    """use_cache=False 强制穿透（CLI --dry-run / 手动补数据用）。"""
    calls: list[int] = []

    def _fake_subprocess() -> list:
        calls.append(1)
        return [{"date": "2026-10-20", "tonnes": 1.0, "ounces": 1.0}]

    monkeypatch.setattr(mod, "_fetch_comex_via_subprocess", _fake_subprocess)
    fetch_comex_inventory(use_cache=False)
    fetch_comex_inventory(use_cache=False)
    assert len(calls) == 2


def test_fetch_raises_when_source_down(monkeypatch) -> None:
    """源不可用且无缓存 → 抛 GoldInventorySourceError。

    ⚠ 这条是「宁缺勿假」的守门断言：如果哪天有人图省事加了 mock 回退，
    这里会直接红 —— 那正是首页会把假库存当真信号用的起点。
    """
    monkeypatch.setattr(mod, "_fetch_comex_via_subprocess", lambda: None)
    with pytest.raises(GoldInventorySourceError):
        fetch_comex_inventory()


def test_fetch_raises_when_all_rows_unparseable(monkeypatch) -> None:
    """子进程成功但一行都解析不出 → 同样抛错，不当「空数据」返回。"""
    monkeypatch.setattr(mod, "_fetch_comex_via_subprocess", lambda: [{"date": "zzz"}])
    with pytest.raises(GoldInventorySourceError):
        fetch_comex_inventory()


def test_fetch_falls_back_to_fresh_cache_when_source_down(monkeypatch) -> None:
    """源挂了但缓存还在 TTL 内 → 返回旧值，**并**是降级而非静默。"""
    state = {"up": True}

    def _fake_subprocess() -> list:
        if not state["up"]:
            return None
        return [{"date": "2026-10-20", "tonnes": 727.96, "ounces": 1.0}]

    monkeypatch.setattr(mod, "_fetch_comex_via_subprocess", _fake_subprocess)
    fetch_comex_inventory()  # 填缓存
    state["up"] = False
    # 缓存命中 → 不抛，返回上一次的值
    out = fetch_comex_inventory()
    assert out[0].tonnes == 727.96


# ──────────────── 子进程模板 ────────────────


def test_subprocess_template_emits_json() -> None:
    """模板脚本真的能跑通并吐可解析 JSON（不是只断言字符串里有没有字段名）。

    断言「模板里有 'COMEX黄金库存量-吨'」这种只测字符串的检查就是门禁假绿：
    列名改了照样绿，跑起来才炸。这里真起子进程。

    需要外网。离线时**显式 skip 并打印原因**（不静默吞）—— 豁免必须看得见，
    否则「因为没网所以这条没测」和「测过了」在报告里长得一模一样。
    """
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, "-c", mod._TEMPLATE], capture_output=True, text=True, timeout=120
    )
    if res.returncode != 0:
        stderr = (res.stderr or "").strip()[:200]
        if "ConnectionError" in stderr or "Max retries" in stderr or "Name or service" in stderr:
            pytest.skip(f"[豁免] COMEX 源不可达，本条未验证（akshare 子进程: {stderr}）")
        pytest.fail(f"子进程失败: {stderr}")

    out = json.loads(res.stdout)
    assert isinstance(out, list) and out
    assert {"date", "tonnes", "ounces"} <= set(out[0])
    assert len(out[0]["date"]) == 10
    assert isinstance(out[0]["tonnes"], float) and out[0]["tonnes"] > 0


def test_inventory_point_is_frozen() -> None:
    """dataclass(frozen=True) —— 观测点不可变，缓存里的对象不会被调用方改脏。"""
    p = InventoryPoint(inv_date=date(2026, 10, 20), tonnes=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.tonnes = 2.0  # type: ignore[misc]


def test_fetch_is_sync_not_async() -> None:
    """fetcher 是同步函数（内部 subprocess.run），service 层用 to_thread 包。

    这条断言钉住调用约定：写成 async 会让 asyncio.to_thread 里包一个协程
    直接炸，而那种错误在测试里不明显、到运行时才显形。
    """
    assert not asyncio.iscoroutinefunction(fetch_comex_inventory)
