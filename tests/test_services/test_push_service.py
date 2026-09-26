"""V0.72.0 P3-b：PushService 单元测试。

mock pywebpush + VAPID 密钥对；不真实推送（CI 友好）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.push import PushKeys, PushSubscriptionIn
from app.services.push import PushService, generate_vapid_keys

# ───────────────────── Helper ─────────────────────


def _mock_repo() -> MagicMock:
    """Mock PushSubscriptionRepository。"""
    repo = MagicMock()
    repo.upsert = AsyncMock(return_value=MagicMock(id=1))
    repo.list_active = AsyncMock(return_value=[])
    repo.delete_by_endpoint = AsyncMock(return_value=True)
    repo.archive_by_endpoint = AsyncMock(return_value=True)
    return repo


def _sub_in(endpoint: str = "https://fcm.googleapis.com/fcm/send/abc123") -> PushSubscriptionIn:
    return PushSubscriptionIn(
        endpoint=endpoint,
        keys=PushKeys(
            p256dh="BNcRdreALRFXTkOOUHK1EtK2wtz5B4PuJUXF4CkX66TYkQbbjBnuCbXn1TnsJwdcUM_6g8LQvb2KkS3exLyu1x8",
            auth="tBHItJI5svbpez7KI4CCXg",
        ),
        user_agent="Mozilla/5.0 (X11; Linux x86_64) test",
    )


# ───────────────────── VAPID 密钥生成测试 ─────────────────────


def test_generate_vapid_keys_returns_pair() -> None:
    """generate_vapid_keys 生成一对：私钥 PEM + 公钥 base64url。"""
    keys = generate_vapid_keys()
    assert keys.private_key.startswith("-----BEGIN")
    assert "PRIVATE KEY" in keys.private_key
    assert len(keys.public_key) > 80  # base64url 编码的 EC P-256 未压缩点 ~88 字符


def test_generate_vapid_keys_unique_per_call() -> None:
    """每次生成不同密钥对。"""
    a = generate_vapid_keys()
    b = generate_vapid_keys()
    assert a.private_key != b.private_key
    assert a.public_key != b.public_key


# ───────────────────── PushService 单元测试 ─────────────────────


async def test_subscribe_calls_repo_upsert() -> None:
    """subscribe 走 repo.upsert，返回 id。"""
    repo = _mock_repo()
    service = PushService(repo=repo)
    sub_in = _sub_in()
    sid = await service.subscribe(sub_in)
    assert sid == 1
    repo.upsert.assert_awaited_once()
    call_kwargs = repo.upsert.await_args.kwargs
    assert call_kwargs["endpoint"] == sub_in.endpoint
    assert call_kwargs["p256dh"] == sub_in.keys.p256dh


async def test_unsubscribe_calls_repo_delete() -> None:
    """unsubscribe 走 repo.delete_by_endpoint。"""
    repo = _mock_repo()
    service = PushService(repo=repo)
    ok = await service.unsubscribe("https://example.com/abc")
    assert ok is True
    repo.delete_by_endpoint.assert_awaited_once_with("https://example.com/abc")


async def test_deliver_skips_empty_subscriptions() -> None:
    """空订阅列表：返回 (0, 0)，不发任何请求。"""
    repo = _mock_repo()
    service = PushService(repo=repo)
    keys = generate_vapid_keys()
    sent, failed = await service.deliver(
        subscriptions=[],
        vapid=keys,
        subject="t",
        body="b",
    )
    assert (sent, failed) == (0, 0)


async def test_deliver_calls_pywebpush_per_subscription() -> None:
    """deliver 对每个订阅调一次 pywebpush。"""
    repo = _mock_repo()
    sub1 = MagicMock(endpoint="https://fcm.example/abc", p256dh="x", auth="y")
    sub2 = MagicMock(endpoint="https://fcm.example/def", p256dh="x2", auth="y2")
    service = PushService(repo=repo)
    keys = generate_vapid_keys()

    with patch("app.services.push._send_one", new=AsyncMock(return_value=True)) as mock_send:
        sent, failed = await service.deliver(
            subscriptions=[sub1, sub2],
            vapid=keys,
            subject="t",
            body="b",
        )
    assert sent == 2
    assert failed == 0
    assert mock_send.await_count == 2


async def test_deliver_handles_exceptions() -> None:
    """deliver 内部异常 → 计 failed，不向上抛。"""
    repo = _mock_repo()
    sub1 = MagicMock(endpoint="https://fcm.example/abc", p256dh="x", auth="y")
    service = PushService(repo=repo)
    keys = generate_vapid_keys()

    with patch(
        "app.services.push._send_one",
        new=AsyncMock(side_effect=Exception("network down")),
    ):
        sent, failed = await service.deliver(
            subscriptions=[sub1],
            vapid=keys,
            subject="t",
            body="b",
        )
    assert sent == 0
    assert failed == 1


# ───────────────────── Schema 校验 ─────────────────────


def test_push_subscription_in_rejects_short_p256dh() -> None:
    """PushKeys.p256dh < 10 字符：ValidationError。"""
    with pytest.raises(ValidationError):
        PushSubscriptionIn(
            endpoint="https://fcm.example/abc",
            keys=PushKeys(p256dh="short", auth="1234567890"),
        )


def test_push_subscription_in_endpoint_required() -> None:
    """endpoint 缺失 → ValidationError。"""
    with pytest.raises(ValidationError):
        PushSubscriptionIn(
            endpoint="",
            keys=PushKeys(p256dh="BNcBnuDlXXXXXXXXXXXXXXXXXX", auth="tBHItJI5svbp"),
        )
