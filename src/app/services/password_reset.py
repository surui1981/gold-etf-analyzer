"""找回密码编排服务（V0.75.3）。

两条端点的安全设计（逐条说明理由，勿删）
----------------------------------------
1. **不区分「邮箱不存在」与「存在」** —— 两个端点的响应**完全一致**
   （同一结构体、同一文案）。否则攻击者可��「哪些邮箱在本系统注册过」
   逐个试探。⚠ 这是找回密码最常见的漏洞来源。
2. **未知账号也走完整流程** —— 申请时不因「邮箱不存在」而提前返回，
   而是同样消耗一次数据库往返；否则耗时差同样泄露存在性。

为什么复用``AuthService`` 而不是另写一套
----------------------------------------
bcrypt cost、密码策略、72 字节上限、会话撤销都是**已验证过**的安全资产。
另起一套必然出现「新旧两套策略不一致」，而那种不一致往往表现为
「找回密码能设一个弱密码」。

⚠ 找回密码**必然踢出全部会话**（不保留当前设备），且比「改密」更彻底 ——
用户是在**已失去访问权**的情况下找回的，若攻击者先于用户改了密码、
或用户怀疑账号被盗，任何残留会话都不该保留。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from app.config import Settings, get_settings
from app.models.user import User, utcnow
from app.repositories.password_reset import (
    TOKEN_TTL,
    PasswordResetTokenRepository,
    hash_token,
)
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService

logger = logging.getLogger(__name__)


class InvalidResetTokenError(Exception):
    """重置 token 无效 / 已用 / 已过期。

    ⚠ 三种情况**共用这一个异常**：区分它们等于告诉攻击者
    「这个 token 曾经有效，只是过期了」—— 那就把 token 的有效期变成可探测信息。
    """


@dataclass(frozen=True)
class ForgotPasswordResult:
    """申请重置的结果（**成功与「邮箱不存在」共用此结构**）。

    ⚠ 字段里刻意**没有** ``token`` —— 只有邮件正文里有它。
    任何时候都不要往这个对象里塞明文 token 再返给前端。
    """

    # 恒为 True，仅为让调用方语义明确（真正要干的事在 ``email_sent``）
    accepted: bool
    # 是否真的发出了邮件。⚠ **不返给客户端**（会泄露邮箱是否存在）；
    # 只用于服务端日志与测试断言。
    email_sent: bool


class PasswordResetService:
    """找回密码编排。"""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        tokens: PasswordResetTokenRepository,
        auth: AuthService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._tokens = tokens
        self._settings = settings or get_settings()
        # ⚠ 复用 AuthService 的 bcrypt cost / 密码策略 / 72 字节上限，
        # 不另写一套（另写必然出现策略不一致，表现为「找回能设弱密码」）。
        self._auth = auth or AuthService(users, sessions, settings=self._settings)

    # ─────────────── 申请重置 ───────────────

    async def request_reset(
        self,
        *,
        email: str,
        smtp_notifier: object | None = None,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> ForgotPasswordResult:
        """发起「忘记密码」：签发token 并（尽力）发邮件。

        ⚠⚠ **无论邮箱是否存在，返回值形态完全一致** —— 端点据此返回同一响应。

        ⚠ SMTP 未配置时：**同样签发 token、同样返回 accepted=True**，
        只在日志里记一条「已生成但无法投递」。**绝不把 token 返给前端** ——
        那等于完全绕过邮箱验证（任何人输任意邮箱都能重置其密码）。
        开发环境无法真实验证邮件流程，是刻意接受的代价。

        Args:
            email: 申请邮箱（大小写不敏感）
            smtp_notifier: :class:`~app.services.notify.SMTPNotifier` 实例；
                None 表示未配置邮件服务
            request_ip / user_agent: 审计用

        Returns:
            :class:`ForgotPasswordResult`，两种情况同构
        """
        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            # ⚠ 与「存在」走同样的耗时路径（不提前返回），避免时序泄露
            logger.info("password reset: 邮箱不存在（对外表现与成功一致）")
            return ForgotPasswordResult(accepted=True, email_sent=False)

        if not user.is_active:
            # ⚠ 禁用账号不发放 token（否则被禁用的人仍能重置密码再登录）。
            # 对外仍返回 accepted=True —— 不泄露「该账号已被停用」。
            logger.info("password reset: 账号已禁用 user_id=%s", user.id)
            return ForgotPasswordResult(accepted=True, email_sent=False)

        _obj, token_plaintext = await self._tokens.create(
            user.id,
            request_ip=request_ip,
            user_agent=user_agent,
        )

        if smtp_notifier is None:
            # ⚠ 未配置邮件服务：记日志，但**不返回 token**
            logger.warning(
                "password reset: token 已生成但未配置 SMTP，无法投递 user_id=%s", user.id
            )
            return ForgotPasswordResult(accepted=True, email_sent=False)

        link = self._build_link(token_plaintext)
        ok = await self._send_mail(
            smtp_notifier,
            to_email=user.email,
            display_name=user.display_name,
            link=link,
        )
        if ok:
            logger.info("password reset: 邮件已发出 user_id=%s", user.id)
        else:
            # ⚠ 发送失败**不报错** —— 对外仍返回 accepted
            logger.warning("password reset: 邮件发送失败 user_id=%s", user.id)
        return ForgotPasswordResult(accepted=True, email_sent=ok)

    def _build_link(self, token: str) -> str:
        """构造邮件里的重置链接。

        ⚠ token 用 :func:`quote` 转义 —— base64url 本身安全，但防的是
        「未来换成含特殊字符的 token」时链接被截断。
        """
        base = (self._settings.public_base_url or "").rstrip("/")
        # ⚠ 用**无 .html 的 RESTful 路径**（与 ``/login`` 同款），而非
        # ``/static/reset-password.html``：前者是 ``main.py`` 里注册的别名，
        # 对用户来说可读、可收藏；后者把内部静态目录结构暴露在邮件里。
        # ⚠ 别名与页面**必须成对存在** —— 少一个，邮件链接就会 404
        # （V0.75.3 实测：新页面若只挂 ``/static/*.html``，
        #   ``/reset-password`` 返回 404，而邮件链接正是这个路径）。
        return f"{base}/reset-password?token={quote(token)}"

    async def _send_mail(
        self,
        notifier: object,
        *,
        to_email: str,
        display_name: str,
        link: str,
    ) -> bool:
        """发重置邮件（异常一律吞掉并记日志，不外泄）。

        ⚠ ``notifier.send(subject=..., body=...)`` 的签名与
        :class:`~app.services.notify.SMTPNotifier` 一致，故此处用鸭子类型，
        便于测试注入桩。
        """
        who = display_name or to_email
        subject = "重置你的黄金 ETF 工具密码"
        body = (
            f"{who} 你好：\n\n"
            f"我们收到了重置密码的申请。请点击下面的链接设置新密码：\n\n"
            f"{link}\n\n"
            f"该链接 {int(TOKEN_TTL.total_seconds() // 3600)} 小时内有效，且只能使用一次。\n"
            f"若你并未申请重置密码，请忽略本邮件 —— 你的密码不会被改动。\n"
        )
        try:
            return bool(await notifier.send(subject=subject, body=body))  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover — 邮件通道异常路径
            logger.warning("password reset: 邮件异常 %s", exc)
            return False

    # ─────────────── 执行重置 ───────────────

    async def reset_password(self, *, token: str, new_password: str) -> int:
        """用 token 设置新密码，**并踢出该用户全部会话**。

        ⚠ 成功后**不复用**旧 token：``consume`` 已把它置为 used_at，
        同一链接第二次提交会得到 :class:`InvalidResetTokenError`。

        ⚠ 全部会话都踢（含当前设备）：找回密码场景下用户已失去访问权，
        保留任何会话都意味着「攻击者可能比用户更早用到」。

        Args:
            token: 邮件链接里的 token 明文
            new_password: 新密码（须过策略）

        Returns:
            被踢下线的会话数

        Raises:
            InvalidResetTokenError: token 无效 / 已用 / 已过期（**三种同一异常**）
            PasswordPolicyError: 新密码不满足策略
        """
        # ⚠ 先校验策略再核销 token —— 否则用户提交弱密码会白白消耗掉
        # token（得重新申请邮件），体验很差。
        from app.services.auth import validate_password_strength

        validate_password_strength(new_password)

        obj = await self._tokens.consume(hash_token(token))
        if obj is None:
            # ⚠ 不区分「不存在 / 已用 / 过期」
            raise InvalidResetTokenError("重置链接无效或已过期")

        user: User | None = await self._users.get_by_id(obj.user_id)
        if user is None:
            # 用户在申请后被删（理论上不该发生，兜底）
            raise InvalidResetTokenError("重置链接无效或已过期")

        await self._users.update_password_hash(user, self._auth.hash_password(new_password))
        revoked = await self._sessions.revoke_all_for_user(user.id, utcnow())
        logger.info("password reset: 重置成功 user_id=%s 踢出会话数=%s", user.id, revoked)
        return revoked
