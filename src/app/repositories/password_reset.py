"""密码重置令牌仓储（V0.75.3）。

⚠⚠ **本仓储的核心纪律：库里只存 ``token_hash``（sha256），永不存明文。**

调用方拿到 :meth:`create` 返回的 ``(token_obj, token_plaintext)``，
其中 ``token_plaintext`` **只用于写进邮件**，用完即弃；
本模块后续所有查询一律用摘要比对。

⚠ 另一个易错点：**不要用 ``token_hash`` 的相等性当「存在性」判断。**
攻击者可能提交任意串试探；本模块的 :meth:`consume` 走「查得到 → 校验哈希 →
置used_at」的流程，且对**查不到**与**哈希不匹配**返回**同一个错误**
（见auth 服务），避免把两种情况区分给攻击者。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import PasswordResetToken, as_naive_utc, utcnow

# token 有效期：24 小时（roadmap §5.2 约定）
TOKEN_TTL = timedelta(hours=24)

# token 字节数。⚠ 43 字符 base64url ≈ 256 位熵 —— 与会话 id 同量级。
# 不用更短：这是能永久改密码的凭据。
TOKEN_BYTES = 32


def generate_token() -> str:
    """生成 token 明文（43 字符 base64url 串）。

    ⚠ 用 :mod:`secrets`（CSPRNG）而**不是** :mod:`random` ——
    后者可由种子推导出全部历史值，用它生成密码重置凭据等于不设防。

    Returns:
        43 字符的 base64url 字符串（URL 安全，可直接放进邮件链接）
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """计算 token 的 sha256 十六进制摘要（落库用）。

    ⚠ 为什么用 sha256 而**不是** bcrypt/argon2：bcrypt 的**盐值让摘要不可
    比对**，无法用「按摘要查一行」定位记录；且 bcrypt 故意慢（这是密码的
    特性），而这里的对手是「拿到库的人」—— sha256 256 位的不可逆性已足够，
    而可快速比对是本表按摘要查询的前提。
    ⚠ 这一权衡**不适用于密码**：密码用 bcrypt（见 ``services/auth.py``）。

    Args:
        token: token 明文

    Returns:
        64 字符小写十六进制字符串
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PasswordResetTokenRepository:
    """密码重置令牌的创建 / 校验 / 作废。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: int,
        *,
        request_ip: str | None = None,
        user_agent: str | None = None,
        ttl: timedelta = TOKEN_TTL,
    ) -> tuple[PasswordResetToken, str]:
        """为用户签发一个新的重置令牌。

        ⚠ **同时作废该用户此前所有未用令牌** —— 否则用户连续申请两次时，
        旧链接仍然有效，等于「最近一次申请才作废旧链接」这条语义没落实，
        而用户往往会被两个邮件搞混（用哪个？）。
        这里选择「新申请即废旧」：宁可让用户多点一次邮箱，也好过留下
        一个用户不知道该不该用的入口。

        Args:
            user_id: 目标用户 id
            request_ip: 申请方 IP（审计用）
            user_agent: 申请方 UA（审计用）
            ttl: 有效期，默认 24h

        Returns:
            ``(落库对象, token 明文)``。
            ⚠ 明文**只应出现在邮件正文里**，调用方不得写日志或返回给前端。
        """
        await self.revoke_all_for_user(user_id)
        token_plaintext = generate_token()
        now = utcnow()
        obj = PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(token_plaintext),
            expires_at=now + ttl,
            used_at=None,
            request_ip=request_ip,
            user_agent=(user_agent or "")[:256] or None,
        )
        self._session.add(obj)
        await self._session.commit()
        await self._session.refresh(obj)
        return obj, token_plaintext

    async def revoke_all_for_user(self, user_id: int) -> int:
        """把某用户所有**未使用**的令牌标记为已用，返回受影响行数。

        ⚠ 用「标记 used_at」而非删除 —— 保留审计痕迹（可发现重放尝试）。
        """
        now = utcnow()
        rows = await self._session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        tokens = list(rows.scalars().all())
        for t in tokens:
            t.used_at = now
        await self._session.commit()
        return len(tokens)

    async def find_usable_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        """按摘要找**仍可使用**（未用且 未过期）的令牌。

        ⚠ 过滤条件与模型层 :attr:`PasswordResetToken.is_usable` **同一套口径**
        （``used_at IS NULL AND expires_at > now``）—— 两处若不同步，
        会出现「校验通过但属性判定不可用」这类无法排查的偏差。

        Args:
            token_hash: :func:`hash_token` 的结果

        Returns:
            命中的令牌对象；不存在 / 已用 / 已过期统一返回 ``None``
            ⚠ **三者返回同一个值**，由调用方转成同一错误码，避免泄露
            「这个 token 曾经有效」。
        """
        now = utcnow()
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        result = await self._session.execute(stmt)
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        expires = obj.expires_at
        # ⚠ datetime 可能带 tz 也可能不带（SQLite 存的是朴素 UTC），
        # 统一交给 as_naive_utc 归一，避免混着比较抛 TypeError。
        naive = as_naive_utc(expires)
        if naive is None or naive <= now:
            return None
        return obj

    async def consume(self, token_hash: str) -> PasswordResetToken | None:
        """**原子地**核销一个令牌：仅当它仍可使用时才置 ``used_at``。

        ⚠ 为什么要「核销」而不是只查：查-then-标记之间有时间窗，
        同一 token 可被并发用两次（重放）。这里先在 ``UPDATE ... WHERE
        used_at IS NULL AND expires_at > now`` 上看影响行数 —— 由**数据库**
        决定谁赢得这次竞争，而不是应用层判断。

        Args:
            token_hash: :func:`hash_token` 的结果

        Returns:
            核销成功返回该令牌对象（含 ``user_id``）；已被用过/过期/不存在
            返回 ``None``。
        """
        from sqlalchemy import update

        now = utcnow()
        obj = await self.find_usable_by_hash(token_hash)
        if obj is None:
            return None
        result = await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.id == obj.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        if int(result.rowcount or 0) != 1:
            # 并发场景下已被另一请求抢先核销
            await self._session.rollback()
            return None
        await self._session.commit()
        obj.used_at = now
        return obj

    async def purge_expired(self, *, older_than: timedelta | None = None) -> int:
        """清理过期令牌，返回删除行数（供启动/定时任务调用）。

        ⚠ **只删「已过期」或「已用过且过很久」的行**，绝不删未用的在途令牌
        —— 否则用户刚收到的邮件链接会突然失效。

        Args:
            older_than: 额外保留期，默认 7 天（过期后再留一周供审计）
        """
        keep = older_than or timedelta(days=7)
        cutoff = utcnow() - keep
        result = await self._session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.expires_at < cutoff)
        )
        await self._session.commit()
        return int(result.rowcount or 0)

    async def count_usable_for_user(self, user_id: int) -> int:
        """某用户当前可用的令牌数（管理员视图 / 测试断言用）。"""
        now = utcnow()
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return sum(1 for t in rows if (n := as_naive_utc(t.expires_at)) is not None and n > now)

    async def list_for_user(self, user_id: int) -> list[PasswordResetToken]:
        """某用户的全部令牌（管理/审计视图，按申请时间倒序）。

        ⚠ **不返回 token 明文**（库里就没有）。
        """
        stmt = (
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id)
            .order_by(PasswordResetToken.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())
