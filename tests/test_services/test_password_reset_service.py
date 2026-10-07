"""V0.75.3 找回密码：安全属性回归测试。

本模块锁死的是**四条不可回退的安全属性**（每条都曾是被漏掉的真实风险）：

1. **不泄露账号存在性** —— 存在与不存在的邮箱，``ForgotPasswordResult``
   形态完全一致；邮件只发给真实账号。
2. **SMTP 未配置时不返回 token** —— 否则任何人输入任意邮箱即可重置其密码，
   邮箱验证形同虚设。
3. **token 一次性** —— 核销后同一链接再提交必失败（防重放）。
4. **弱密码被策略拒绝且不消耗 token** —— 否则用户提交一次弱密码就得
   重新去邮箱点一次链接。

⚠ 为什么要单独建文件而不是并入 ``test_auth_service.py``：这四条是
**跨仓储 + 跨服务**的行为（users / sessions / tokens / auth），
混进大文件里容易被后续改动「顺手改掉断言」而不自知。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.config import Settings
from app.repositories.password_reset import (
    TOKEN_TTL,
    PasswordResetTokenRepository,
    generate_token,
    hash_token,
)
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import AuthService, PasswordPolicyError
from app.services.password_reset import InvalidResetTokenError, PasswordResetService

# 测试用强密码（过策略：≥8 位）
GOOD_PW = "Passw0rd!x"
NEW_PW = "NewPassw0rd!x"


class _FakeMail:
    """邮件桩：记录全部发送，便于断言「只发给真实账号」。"""

    def __init__(self, ok: bool = True) -> None:
        self.sent: list[dict[str, str]] = []
        self._ok = ok

    async def send(self, *, subject: str, body: str, trace_id: str | None = None) -> bool:
        self.sent.append({"subject": subject, "body": body})
        return self._ok

    @property
    def last_token(self) -> str:
        """从最后一封邮件正文里抠出 token。"""
        body = self.sent[-1]["body"]
        marker = "token="
        idx = body.index(marker) + len(marker)
        return body[idx:].split("\n")[0].strip()


@pytest.fixture
def svc(db_session) -> PasswordResetService:
    """组装服务（测试库由 conftest 逐用例重建）。"""
    users = UserRepository(db_session)
    sessions = SessionRepository(db_session)
    tokens = PasswordResetTokenRepository(db_session)
    return PasswordResetService(users, sessions, tokens, settings=Settings())


@pytest.fixture
async def alice(db_session, svc: PasswordResetService) -> Any:
    return await UserRepository(db_session).create(
        email="alice@example.com",
        password_hash=svc._auth.hash_password(GOOD_PW),
        display_name="Alice",
    )


# ─────────────── 1. 不泄露账号存在性 ───────────────


async def test_unknown_email_returns_same_shape(db_session, svc, alice) -> None:
    """★ 存在的邮箱与不存在的邮箱，返回值**形态完全一致**。

    若这里让调用方能靠 ``accepted``/异常类型区分，就等于开放
    「哪些邮箱在本系统注册过」的枚举接口。
    """
    mail_hit, mail_miss = _FakeMail(), _FakeMail()
    r_hit = await svc.request_reset(email="alice@example.com", smtp_notifier=mail_hit)
    r_miss = await svc.request_reset(email="nobody@example.com", smtp_notifier=mail_miss)

    assert r_hit.accepted is True
    assert r_miss.accepted is True, "不存在的邮箱也必须 accepted=True"
    # 唯一允许不同的是 email_sent（服务端内部用，不返给客户端）
    assert r_hit.email_sent is True
    assert r_miss.email_sent is False


async def test_mail_only_sent_to_real_account(db_session, svc, alice) -> None:
    """★ 邮件只发给真实存在的账号（未知账号不发信）。"""
    mail_hit, mail_miss = _FakeMail(), _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail_hit)
    await svc.request_reset(email="nobody@example.com", smtp_notifier=mail_miss)

    assert len(mail_hit.sent) == 1
    assert len(mail_miss.sent) == 0


async def test_email_lookup_is_case_insensitive(db_session, svc, alice) -> None:
    """邮箱大小写不敏感（用户常按Caps Lock 输入）。"""
    mail = _FakeMail()
    r = await svc.request_reset(email="ALICE@Example.COM", smtp_notifier=mail)
    assert r.email_sent is True
    assert len(mail.sent) == 1


# ─────────────── 2. SMTP 未配置时不泄露 token ───────────────


async def test_no_smtp_does_not_return_token(db_session, svc, alice) -> None:
    """★★ SMTP 未配置时：accepted=True，但**绝不**把 token 交给调用方。

    这条是本模块最重要的断言：若token 出现在返回值里，
    任何人输入任意邮箱都能重置其密码 —— 邮箱验证被完全绕过。
    """
    r = await svc.request_reset(email="alice@example.com", smtp_notifier=None)

    assert r.accepted is True, "对外形态须与成功路径一致"
    assert r.email_sent is False
    # 对象里不得携带任何凭据
    assert not hasattr(r, "token")
    assert "token" not in r.__dataclass_fields__


async def test_smtp_send_failure_still_accepted(db_session, svc, alice) -> None:
    """⚠ SMTP 抛异常时仍返回 accepted=True（不因投递失败暴露账号存在性）。"""
    r = await svc.request_reset(email="alice@example.com", smtp_notifier=_FakeMail(ok=False))
    assert r.accepted is True
    assert r.email_sent is False


# ─────────────── 3. token 一次性 + 存哈希 ───────────────


async def test_token_stored_as_hash_not_plaintext(db_session, svc, alice) -> None:
    """★★ 库里存的是 sha256 摘要，**不是明文**。

    若存明文，一次库泄漏 = 所有在途账号可被永久重置。
    """
    import sqlalchemy as sa

    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    token = mail.last_token

    rows = (await db_session.execute(sa.text("select token_hash from password_reset_tokens"))).all()
    assert rows, "应有一行 token 记录"
    stored = rows[0][0]
    assert token not in stored, "库中出现了明文 token —— 严重缺陷"
    assert stored == hash_token(token)
    assert len(stored) == 64, "应为 sha256 十六进制长度"


async def test_reset_succeeds_and_revokes_all_sessions(db_session, svc, alice) -> None:
    """重置成功且**踢出该用户全部会话**（找回场景下不保留任何设备）。"""
    sessions = SessionRepository(db_session)
    await sessions.create(user_id=alice.id, expires_at=datetime(2099, 1, 1), session_id="s1")
    await sessions.create(user_id=alice.id, expires_at=datetime(2099, 1, 1), session_id="s2")

    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    revoked = await svc.reset_password(token=mail.last_token, new_password=NEW_PW)

    assert revoked == 2, "两个会话都应被踢"
    live = await sessions.list_active_for_user(alice.id)
    assert live == []


async def test_token_is_single_use(db_session, svc, alice) -> None:
    """★★ 同一token 第二次提交必失败（防重放）。"""
    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    token = mail.last_token

    await svc.reset_password(token=token, new_password=NEW_PW)
    with pytest.raises(InvalidResetTokenError):
        await svc.reset_password(token=token, new_password="ThirdPass1!x")


async def test_new_request_invalidates_previous(db_session, svc, alice) -> None:
    """★ 新申请即作废旧 token（否则用户会被两个邮件搞混）。"""
    m1, m2 = _FakeMail(), _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=m1)
    first = m1.last_token
    await svc.request_reset(email="alice@example.com", smtp_notifier=m2)

    with pytest.raises(InvalidResetTokenError):
        await svc.reset_password(token=first, new_password=NEW_PW)


async def test_expired_token_rejected(db_session, svc, alice) -> None:
    """过期 token 被拒。"""
    tokens = PasswordResetTokenRepository(db_session)
    _obj, plain = await tokens.create(alice.id, ttl=timedelta(seconds=-1))
    with pytest.raises(InvalidResetTokenError):
        await svc.reset_password(token=plain, new_password=NEW_PW)


async def test_garbage_token_rejected(db_session, svc, alice) -> None:
    """任意乱码 token 走同一个异常（不区分「不存在」与「已过期」）。"""
    with pytest.raises(InvalidResetTokenError):
        await svc.reset_password(token="not-a-real-token", new_password=NEW_PW)


async def test_disabled_account_gets_no_token(db_session, svc, alice) -> None:
    """⚠ 已禁用账号不发放 token（否则被禁用的人仍能重置密码再登录）。"""
    users = UserRepository(db_session)
    await users.set_active(alice, is_active=False)
    tokens = PasswordResetTokenRepository(db_session)

    r = await svc.request_reset(email="alice@example.com", smtp_notifier=_FakeMail())
    assert r.accepted is True, "对外仍不暴露「已停用」"
    assert r.email_sent is False
    assert await tokens.count_usable_for_user(alice.id) == 0


# ─────────────── 4. 密码策略：拒绝弱密码且不消耗 token ───────────────


async def test_weak_password_rejected(db_session, svc, alice) -> None:
    """弱密码被策略拒绝。"""
    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    with pytest.raises(PasswordPolicyError):
        await svc.reset_password(token=mail.last_token, new_password="short")


async def test_weak_password_does_not_consume_token(db_session, svc, alice) -> None:
    """★★ 弱密码被拒后token **仍然可用** —— 否则用户白跑一趟邮箱。

    顺序刻意是「先校验策略、再核销 token」。
    """
    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    token = mail.last_token

    with pytest.raises(PasswordPolicyError):
        await svc.reset_password(token=token, new_password="short")

    # 同一 token 换个合规密码应仍可用
    await svc.reset_password(token=token, new_password=NEW_PW)


async def test_new_password_takes_effect(db_session, svc, alice) -> None:
    """重置后新密码可用、旧密码失效。"""
    users = UserRepository(db_session)
    au = AuthService(users, SessionRepository(db_session))
    mail = _FakeMail()
    await svc.request_reset(email="alice@example.com", smtp_notifier=mail)
    await svc.reset_password(token=mail.last_token, new_password=NEW_PW)

    user = await users.get_by_email("alice@example.com")
    assert au.verify_password(NEW_PW, user.password_hash)
    assert not au.verify_password(GOOD_PW, user.password_hash)


# ─────────────── 辅助：token 生成 ───────────────


def test_generate_token_is_url_safe_and_unique() -> None:
    token = generate_token()
    assert len(token) == 43, "应为 32 字节 base64url"
    assert all(c.isalnum() or c in "-_" for c in token), "必须 URL 安全"
    assert token != generate_token(), "两次生成必须不同"


def test_hash_token_is_sha256_hex() -> None:
    """sha256 的标准值 —— 锁定算法，**换算法须同步换迁移**（旧摘要将全部失效）。"""
    assert hash_token("abc") == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_token_ttl_is_24h() -> None:
    """roadmap §5.2 约定 24h TTL。"""
    assert timedelta(hours=24) == TOKEN_TTL
