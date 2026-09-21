"""通知推送（V0.72.0）：Notifier 协议 + SMTP 邮件 + Server 酱微信。

每渠道独立类实现，``NotifierFactory.create(channel)`` 根据配置返回实例。
失败退避策略：5s / 30s / 5min 三次，全失败返回 False（由 AlertDispatcher 写 telemetry）。
"""

from __future__ import annotations

import asyncio
import os
from email.mime.text import MIMEText
from typing import Protocol

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)


class Notifier(Protocol):
    """通知器协议：所有推送渠道实现此接口。"""

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool: ...

    @property
    def channel(self) -> str: ...


class SMTPNotifier:
    """SMTP 邮件推送（aiosmtplib 异步）。"""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        use_tls: bool = True,
        sender: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._use_tls = use_tls
        self._sender = sender or user

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool:
        import aiosmtplib  # 延迟导入，未配置 SMTP 时不强制加载

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = self._user
        try:
            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                use_tls=self._use_tls,
            )
            logger.info(
                "SMTP send OK: host=%s to=%s subject=%s trace_id=%s",
                self._host,
                self._user,
                subject,
                trace_id,
            )
            return True
        except Exception as exc:
            logger.warning(
                "SMTP send failed: host=%s err=%s trace_id=%s",
                self._host,
                exc,
                trace_id,
            )
            return False

    @property
    def channel(self) -> str:
        return "email"


class ServerChanNotifier:
    """Server 酱微信推送（https://sctapi.ftqq.com/{sendkey}.send）。

    参考 https://sct.ftqq.com/ ：返回 JSON ``{"code": 0, "message": "..."}`` 表示成功。
    """

    ENDPOINT = "https://sctapi.ftqq.com/{sendkey}.send"
    TIMEOUT_SECONDS = 10.0

    def __init__(self, sendkey: str) -> None:
        self._sendkey = sendkey

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    self.ENDPOINT.format(sendkey=self._sendkey),
                    data={"title": subject, "desp": body},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Server酱 HTTP %s: sendkey=%s... trace_id=%s",
                        resp.status_code,
                        self._sendkey[:8],
                        trace_id,
                    )
                    return False
                payload = resp.json()
                if payload.get("code") != 0:
                    logger.warning(
                        "Server酱 code=%s message=%s trace_id=%s",
                        payload.get("code"),
                        payload.get("message"),
                        trace_id,
                    )
                    return False
                logger.info(
                    "Server酱 send OK: sendkey=%s... subject=%s trace_id=%s",
                    self._sendkey[:8],
                    subject,
                    trace_id,
                )
                return True
        except Exception as exc:
            logger.warning(
                "Server酱 send failed: err=%s trace_id=%s",
                exc,
                trace_id,
            )
            return False

    @property
    def channel(self) -> str:
        return "wechat"


# V0.72.0 P3-b：退避时间表（秒）。三次重试：5s / 30s / 5min。
_RETRY_BACKOFFS: tuple[float, ...] = (5.0, 30.0, 300.0)


async def send_with_retry(
    notifier: Notifier,
    *,
    subject: str,
    body: str,
    trace_id: str | None = None,
) -> bool:
    """单渠道发送 + 退避重试（最多 3 次）。全失败返回 False。"""
    for attempt in range(1, len(_RETRY_BACKOFFS) + 1):
        ok = await notifier.send(subject=subject, body=body, trace_id=trace_id)
        if ok:
            return True
        if attempt < len(_RETRY_BACKOFFS):
            backoff = _RETRY_BACKOFFS[attempt - 1]
            logger.info(
                "Notifier %s retry %s/%s after %.0fs",
                notifier.channel,
                attempt + 1,
                len(_RETRY_BACKOFFS),
                backoff,
            )
            await asyncio.sleep(backoff)
    return False


class NotifierFactory:
    """从环境变量构建 Notifier 实例。配置缺失返回 None（dev 友好）。"""

    @staticmethod
    def create(channel: str) -> Notifier | None:
        if channel == "email":
            host = os.getenv("SMTP_HOST")
            if not host:
                return None
            try:
                port = int(os.getenv("SMTP_PORT", "465"))
            except ValueError:
                logger.warning("SMTP_PORT invalid, fallback 465")
                port = 465
            return SMTPNotifier(
                host=host,
                port=port,
                user=os.getenv("SMTP_USER", ""),
                password=os.getenv("SMTP_PASS", ""),
                use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
                sender=os.getenv("NOTIFY_FROM", ""),
            )
        if channel == "wechat":
            sendkey = os.getenv("SERVERCHAN_SENDKEY")
            if not sendkey:
                return None
            return ServerChanNotifier(sendkey=sendkey)
        return None

    @staticmethod
    def create_all(channels: list[str]) -> list[Notifier]:
        """从渠道列表创建所有可用 Notifier（缺配置的渠道跳过）。"""
        out: list[Notifier] = []
        for ch in channels:
            n = NotifierFactory.create(ch)
            if n is not None:
                out.append(n)
        return out


__all__ = [
    "Notifier",
    "NotifierFactory",
    "SMTPNotifier",
    "ServerChanNotifier",
    "send_with_retry",
]
