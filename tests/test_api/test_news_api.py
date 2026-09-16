"""消息面打分 API 集成测试（V0.65.0：每日 3 次机会 + 1:2:3 加权）。

覆盖：
- 空态：scored=false、剩余 3 次、next_slot=1
- 按序占用槽位 1/2/3，当日有效分值按 1:2:3 加权
- 三次用尽后留空 slot 提交 → 400（不再静默覆盖）
- 显式 slot 覆盖修正
- DELETE 撤销并重新归一权重；撤销不存在槽位 → 404
- 历史记录接口；参数校验 422
"""

from httpx import AsyncClient

API = "/api/v1/news-score"


async def test_empty_state(client: AsyncClient) -> None:
    """未打分：中性 50、剩余 3 次、下一个槽位为 1。"""
    r = await client.get(API)
    assert r.status_code == 200
    d = r.json()
    assert d["scored"] is False
    assert d["score"] == 50.0
    assert d["slots"] == []
    assert d["used_slots"] == 0
    assert d["remaining_slots"] == 3
    assert d["next_slot"] == 1


async def test_auto_slot_sequence_and_weighting(client: AsyncClient) -> None:
    """三次打分依次占用 slot 1/2/3，有效分值 = (1×40 + 2×60 + 3×70) / 6。"""
    for score in (40, 60):
        r = await client.put(API, json={"score": score, "direction": "neutral"})
        assert r.status_code == 200

    r = await client.put(API, json={"score": 70, "direction": "bullish", "notes": "加息落地"})
    assert r.status_code == 200
    d = r.json()

    assert [s["slot"] for s in d["slots"]] == [1, 2, 3]
    assert [s["weight"] for s in d["slots"]] == [1, 2, 3]
    assert d["used_slots"] == 3
    assert d["remaining_slots"] == 0
    assert d["next_slot"] is None
    assert d["weighted"] is True
    assert d["score"] == 61.7
    assert d["formula"] == "(1×40 + 2×60 + 3×70) ÷ 6"
    assert d["slots"][2]["scored_at"]  # 记录打分时刻


async def test_fourth_submit_rejected(client: AsyncClient) -> None:
    """三次用尽后留空 slot → 400，提示指定槽位修改。"""
    for score in (40, 60, 70):
        await client.put(API, json={"score": score, "direction": "neutral"})

    r = await client.put(API, json={"score": 80, "direction": "bullish"})
    assert r.status_code == 400
    assert "3 次打分机会已用完" in r.json()["detail"]


async def test_explicit_slot_overwrite(client: AsyncClient) -> None:
    """显式 slot=2 覆盖修正，不占用新槽位。"""
    for score in (40, 60, 70):
        await client.put(API, json={"score": score, "direction": "neutral"})

    r = await client.put(API, json={"score": 45, "direction": "neutral", "slot": 2})
    assert r.status_code == 200
    d = r.json()

    assert [round(s["score"]) for s in d["slots"]] == [40, 45, 70]
    assert d["used_slots"] == 3
    assert d["score"] == 56.7  # (1×40 + 2×45 + 3×70) / 6


async def test_delete_slot_reweighs(client: AsyncClient) -> None:
    """撤销 slot=2 → 释放槽位，剩余按 1:3 归一。"""
    for score in (40, 60, 70):
        await client.put(API, json={"score": score, "direction": "neutral"})

    r = await client.delete(API + "/2")
    assert r.status_code == 200
    d = r.json()

    assert [s["slot"] for s in d["slots"]] == [1, 3]
    assert d["used_slots"] == 2
    assert d["next_slot"] == 2
    assert d["score"] == 62.5  # (1×40 + 3×70) / 4

    r2 = await client.delete(API + "/2")
    assert r2.status_code == 404


async def test_history_endpoint(client: AsyncClient) -> None:
    """历史记录接口返回跨日打分，按时间倒序。"""
    await client.put(API, json={"score": 55, "direction": "neutral", "notes": "第一次"})
    await client.put(API, json={"score": 75, "direction": "bullish", "notes": "第二次"})

    r = await client.get(API + "/history?limit=10")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert d["items"][0]["slot"] == 2
    assert d["items"][0]["weight"] == 2
    assert d["items"][1]["slot"] == 1


async def test_validation_errors(client: AsyncClient) -> None:
    """分值越界 / 槽位越界 → 422。"""
    assert (await client.put(API, json={"score": 101, "direction": "neutral"})).status_code == 422
    assert (await client.put(API, json={"score": -1, "direction": "neutral"})).status_code == 422
    assert (
        await client.put(API, json={"score": 50, "direction": "neutral", "slot": 4})
    ).status_code == 422
