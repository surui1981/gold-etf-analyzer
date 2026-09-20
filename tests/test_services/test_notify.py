"""V0.72.0 P3-b：Notifier 协议 + SMTP + Server 酱 + 工厂 + 退避重试。

mock SMTP/Server酱，无真实网络（CI 友好，与 irfcl_fetcher / h15_fetcher 同 pattern）。
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notify import (
    Notifier,
    NotifierFactory,
    ServerChanNotifier,
    SMTPNotifier,
    send_with_retry,
)

# ───────────────────── NotifierFactory 测试 ─────────────────────


def test_factory_create_email_with_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP_HOST 设了就返回 SMTPNotifier。"""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("NOTIFY_FROM", "alerts@example.com")

    n = NotifierFactory.create("email")
    assert isinstance(n, SMTPNotifier)
    assert n._host == "smtp.example.com"
    assert n._port == 587
    assert n._use_tls is True
    assert n._sender == "alerts@example.com"


def test_factory_create_email_without_host() -> None:
    """SMTP_HOST 为空返回 None（dev 友好）。"""
    with patch.dict(os.environ, {"SMTP_HOST": ""}, clear=False):
        assert NotifierFactory.create("email") is None


def test_factory_create_wechat_with_sendkey(monkeypatch: pytest.MonkeyPatch) -> None:
    """SERVERCHAN_SENDKEY 设了就返回 ServerChanNotifier。"""
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCT123456")
    n = NotifierFactory.create("wechat")
    assert isinstance(n, ServerChanNotifier)
    assert n._sendkey == "SCT123456"


def test_factory_create_wechat_without_sendkey() -> None:
    """SERVERCHAN_SENDKEY 为空返回 None。"""
    with patch.dict(os.environ, {"SERVERCHAN_SENDKEY": ""}, clear=False):
        assert NotifierFactory.create("wechat") is None


def test_factory_create_unknown_channel() -> None:
    """未知渠道返回 None。"""
    assert NotifierFactory.create("browser") is None
    assert NotifierFactory.create("webpush") is None
    assert NotifierFactory.create("nonsense") is None


# ───────────────────── SMTPNotifier 测试 ─────────────────────


async def test_smtp_send_success() -> None:
    """SMTP 发送成功返回 True。"""
    notifier = SMTPNotifier(
        host="smtp.example.com",
        port=465,
        user="u@example.com",
        password="pw",
        sender="alerts@example.com",
    )

    with patch("aiosmtplib.send", new=AsyncMock(return_value=None)) as mock_send:
        ok = await notifier.send(subject="测试", body="正文")
        assert ok is True
        assert mock_send.await_count == 1


async def test_smtp_send_failure_returns_false() -> None:
    """SMTP 抛异常返回 False（不向上抛）。"""
    notifier = SMTPNotifier("smtp.example.com", 465, "u@e.com", "pw")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=Exception("auth failed"))):
        ok = await notifier.send(subject="t", body="b")
        assert ok is False


# ───────────────────── ServerChanNotifier 测试 ─────────────────────


async def test_serverchan_send_success() -> None:
    """Server酱 HTTP 200 + code=0 返回 True。"""
    notifier = ServerChanNotifier("SCT123456")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"code": 0, "message": "ok"}

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        MockClient.return_value.__aenter__.return_value = mock_client
        MockClient.return_value.__aexit__.return_value = None

        ok = await notifier.send(subject="测试", body="正文")
        assert ok is True


async def test_serverchan_send_http_error() -> None:
    """Server酱 HTTP 非 200 返回 False。"""
    notifier = ServerChanNotifier("SCT123456")

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        MockClient.return_value.__aenter__.return_value = mock_client
        MockClient.return_value.__aexit__.return_value = None

        ok = await notifier.send(subject="t", body="b")
        assert ok is False


async def test_serverchan_send_app_error() -> None:
    """Server酱 HTTP 200 但 code != 0 返回 False。"""
    notifier = ServerChanNotifier("SCT_BAD")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"code": 1, "message": "invalid sendkey"}

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        MockClient.return_value.__aenter__.return_value = mock_client
        MockClient.return_value.__aexit__.return_value = None

        ok = await notifier.send(subject="t", body="b")
        assert ok is False


# ───────────────────── 退避重试测试 ─────────────────────


async def test_send_with_retry_success_no_retry() -> None:
    """第一次就成功：不重试。"""
    notifier = _MockNotifier(success=True)
    ok = await send_with_retry(notifier, subject="t", body="b")
    assert ok is True
    assert notifier.calls == 1


async def test_send_with_retry_eventually_success() -> None:
    """第二次重试成功：返回 True。"""
    notifier = _MockNotifier(success=False, success_after=2)
    # 缩短退避时间（patch）以加速测试
    with patch("app.services.notify._RETRY_BACKOFFS", (0.0, 0.0, 0.0)):
        ok = await send_with_retry(notifier, subject="t", body="b")
    assert ok is True
    assert notifier.calls == 2


async def test_send_with_retry_all_fail_returns_false() -> None:
    """三次全部失败：返回 False。"""
    notifier = _MockNotifier(success=False)
    # 缩短退避时间（patch）以加速测试
    with patch("app.services.notify._RETRY_BACKOFFS", (0.0, 0.0, 0.0)):
        ok = await send_with_retry(notifier, subject="t", body="b")
    assert ok is False
    assert notifier.calls == 3


# ───────────────────── Helper ─────────────────────


class _MockNotifier(Notifier):
    """测试用：可控制成功时机的 Notifier。"""

    def __init__(self, success: bool = True, success_after: int = 0) -> None:
        self._success = success
        self._success_after = success_after
        self.calls = 0

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool:
        self.calls += 1
        if self._success_after and self.calls >= self._success_after:
            return True
        return self._success

    @property
    def channel(self) -> str:
        return "mock"