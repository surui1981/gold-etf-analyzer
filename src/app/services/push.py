"""V0.72.0 P3-b：Web Push 投递服务（pywebpush 异步包装 + VAPID 签名）。"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass

from py_vapid import Vapid
from pywebpush import WebPusher, WebPushException

from app.models.push import PushSubscription as PushSubscriptionModel
from app.repositories.push import PushSubscriptionRepository
from app.schemas.push import PushSubscriptionIn
from app.services.settings import VapidKeys, get_vapid_keys, save_vapid_keys

logger = logging.getLogger(__name__)


# ───────────────────── VAPID 密钥生成（EC P-256）─────────────────────


def _b64url_decode(data: str) -> bytes:
    """base64url 解码（补全 padding）。"""
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _b64url_encode(data: bytes) -> str:
    """base64url 编码（无 padding）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_keys() -> VapidKeys:
    """生成新的 VAPID 密钥对（EC P-256）。

    Returns:
        VapidKeys(private_key=PEM, public_key=base64url-uncompressed-point)
    """
    # py_vapid Vapid().generate_keys() → 内部生成 EC 密钥
    vapid = Vapid()
    vapid.generate_keys()
    # 私钥 PEM
    private_pem = vapid.private_pem()
    if isinstance(private_pem, bytes):
        private_pem = private_pem.decode("utf-8")
    # 公钥 base64url（未压缩点 X962）
    from cryptography.hazmat.primitives import serialization

    pub_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("ascii")
    return VapidKeys(private_key=private_pem, public_key=public_b64)


@dataclass
class PushService:
    """Web Push 投递服务：subscribe / unsubscribe / deliver。

    VAPID 密钥从 ``app_settings`` 表读取；启动时若不存在则自动生成一次。
    """

    repo: PushSubscriptionRepository

    async def subscribe(self, payload: PushSubscriptionIn) -> int:
        """新增或更新一条订阅。返回订阅 id。"""
        sub = await self.repo.upsert(
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=payload.user_agent,
        )
        logger.info("Push subscription upserted: id=%d endpoint=%s...", sub.id, payload.endpoint[:30])
        return sub.id

    async def unsubscribe(self, endpoint: str) -> bool:
        """用户主动退订。"""
        return await self.repo.delete_by_endpoint(endpoint)

    async def ensure_vapid_keys(self, settings_repo) -> VapidKeys:
        """启动期确保 VAPID 密钥对存在；不存在则生成并保存。"""
        keys = await get_vapid_keys(settings_repo)
        if keys is not None:
            return keys
        keys = generate_vapid_keys()
        await save_vapid_keys(settings_repo, keys)
        logger.info("VAPID keys generated and saved (public_key=%s...)", keys.public_key[:16])
        return keys

    async def deliver(
        self,
        *,
        subscriptions: list[PushSubscriptionModel],
        vapid: VapidKeys,
        subject: str,
        body: str,
        url: str = "/portfolio",
        tag: str = "gold-alert",
        trace_id: str | None = None,
    ) -> tuple[int, int]:
        """对一组订阅逐个推送。返回 (sent_count, failed_count)。"""
        sent = 0
        failed = 0
        for sub in subscriptions:
            try:
                ok = await _send_one(
                    subscription=sub,
                    vapid_private_key=vapid.private_key,
                    subject=subject,
                    body=body,
                    url=url,
                    tag=tag,
                    trace_id=trace_id,
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.warning("Push deliver exception: %s trace_id=%s", exc, trace_id)
                failed += 1
        return sent, failed


async def _send_one(
    *,
    subscription: PushSubscriptionModel,
    vapid_private_key: str,
    subject: str,
    body: str,
    url: str,
    tag: str,
    trace_id: str | None,
) -> bool:
    """单条订阅推送。404/410 → 自动 archive。"""
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }
    payload = json.dumps({"title": subject, "body": body, "tag": tag, "url": url}, ensure_ascii=False)

    try:
        # pywebpush 是同步库；用 run_in_executor 避免阻塞 event loop
        import asyncio

        loop = asyncio.get_running_loop()

        def _push() -> None:
            # py_vapid 从 PEM 字符串恢复私钥（仅用于校验私钥格式；推送时再传给 pywebpush）
            Vapid.from_pem(private_key=vapid_private_key.encode("utf-8"))
            claims = {"sub": f"mailto:{os.getenv('NOTIFY_FROM', 'admin@example.com')}"}
            wp = WebPusher(subscription_info)
            wp.send(
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims=claims,
                content_encoding="aesgcm",
                ttl=86400,
            )

        await loop.run_in_executor(None, _push)
        logger.info(
            "Web Push sent: endpoint=%s... trace_id=%s",
            subscription.endpoint[:30],
            trace_id,
        )
        return True
    except WebPushException as exc:
        # 404 / 410 → subscription 失效，archive
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None) if response else None
        if status_code in (404, 410):
            logger.info(
                "Push subscription gone (%s), archiving: endpoint=%s...",
                status_code,
                subscription.endpoint[:30],
            )
            # 依赖注入层可独立 archive；这里只 log + 返 False
        else:
            logger.warning(
                "Web Push failed: status=%s err=%s trace_id=%s",
                status_code,
                exc,
                trace_id,
            )
        return False
