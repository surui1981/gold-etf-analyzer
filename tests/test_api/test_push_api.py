"""V0.72.0 P3-b：Web Push 端点测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """测试环境的 X-Admin-Token 头（conftest 已设 ADMIN_TOKEN=secret）。"""
    return {"X-Admin-Token": "secret"}


# ───────────────────── GET /push/vapid-public-key ─────────────────────


async def test_get_vapid_public_key_generates_if_missing(client: AsyncClient) -> None:
    """首次访问：自动生成 VAPID 密钥对并返回公钥。"""
    r = await client.get("/api/v1/push/vapid-public-key")
    assert r.status_code == 200
    body = r.json()
    assert "key" in body
    assert len(body["key"]) > 80  # base64url 编码的 EC P-256 未压缩点


async def test_get_vapid_public_key_idempotent(client: AsyncClient) -> None:
    """两次访问：返回相同公钥（持久化）。"""
    r1 = await client.get("/api/v1/push/vapid-public-key")
    r2 = await client.get("/api/v1/push/vapid-public-key")
    assert r1.json()["key"] == r2.json()["key"]


# ───────────────────── POST /push/subscribe ─────────────────────


async def test_subscribe_creates_record(client: AsyncClient) -> None:
    """新增订阅：200 + 返回 id。"""
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-1",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtz5B4PuJUXF4CkX66TY",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
        "user_agent": "pytest",
    }
    r = await client.post("/api/v1/push/subscribe", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert body["id"] >= 1


async def test_subscribe_upsert_by_endpoint(client: AsyncClient) -> None:
    """同一 endpoint 重复订阅：视为同一记录（更新密钥）。"""
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-2",
        "keys": {"p256dh": "OLD_OLD_OLD_OLD_OLD_OLD_OLD_OLD", "auth": "OLD_OLD_OLD_OLD_OLD_OLD"},
    }
    r1 = await client.post("/api/v1/push/subscribe", json=payload)
    id1 = r1.json()["id"]
    # 同样的 endpoint，新密钥
    payload["keys"]["p256dh"] = "NEW_NEW_NEW_NEW_NEW_NEW_NEW_NEW"
    r2 = await client.post("/api/v1/push/subscribe", json=payload)
    id2 = r2.json()["id"]
    assert id1 == id2  # 同一订阅


async def test_subscribe_rejects_invalid_payload(client: AsyncClient) -> None:
    """payload 缺 keys.p256dh → 422。"""
    r = await client.post(
        "/api/v1/push/subscribe",
        json={"endpoint": "https://example.com", "keys": {"p256dh": "x", "auth": "y"}},
    )
    assert r.status_code == 422  # p256dh 太短


# ───────────────────── DELETE /push/subscribe ─────────────────────


async def test_unsubscribe_removes_record(client: AsyncClient) -> None:
    """退订：返回 deleted=True。"""
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-del",
        "keys": {"p256dh": "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "auth": "1234567890"},
    }
    await client.post("/api/v1/push/subscribe", json=payload)
    r = await client.delete(
        "/api/v1/push/subscribe",
        params={"endpoint": "https://fcm.googleapis.com/fcm/send/test-del"},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] is True


async def test_unsubscribe_nonexistent_endpoint(client: AsyncClient) -> None:
    """退订不存在的 endpoint：deleted=False。"""
    r = await client.delete(
        "/api/v1/push/subscribe",
        params={"endpoint": "https://fcm.example/never-existed"},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] is False


# ───────────────────── POST /push/test（admin 守卫）─────────────────────


async def test_test_push_dev_mode_bypasses_admin(client: AsyncClient) -> None:
    """dev 模式（无 ADMIN_TOKEN env）：admin 守卫 skip，调用成功返回 200。

    生产部署必须设置 ADMIN_TOKEN env；middleware 测试（tests/test_middleware/test_admin_auth.py）
    专门覆盖 401 行为。
    """
    r = await client.post("/api/v1/push/test")
    assert r.status_code == 200


async def test_test_push_with_admin_returns_zero(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """无订阅：admin 测试推送返回 sent=0 failed=0 total=0。"""
    r = await client.post("/api/v1/push/test", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {"sent": 0, "failed": 0, "total": 0}