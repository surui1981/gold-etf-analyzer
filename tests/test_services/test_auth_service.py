"""认证服务测试（V0.75.0 认证骨架 · 服务层）。

覆盖：
- 密码哈希（bcrypt 前缀 / cost / 校验 / 损坏哈希不抛错）
- 密码策略（过短 / 纯数字 / 弱口令黑名单 / 超 72 字节）
- 邮箱规范化与格式校验
- 注册（首个用户为 owner / 重复邮箱 / 关闭自助注册 / 唯一索引兜底）
- 登录（成功写 last_login_at / 密码错 / 账号不存在 / 已禁用 —— 三者文案一致）
- 登录节流（达阈值锁定 / 锁定期内即使密码正确也拒绝 / 成功后清零）
- 会话校验（有效 / 过期 / 已撤销 / 用户被禁用 / 不存在的 ID）
- 登出（幂等）与 logout_all（保留当前会话）
- 改密（当前密码校验 / 踢出其他设备 / 新旧密码各自的可登录性）
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import get_settings
from app.models.user import ROLE_MEMBER, ROLE_OWNER, utcnow
from app.repositories.user import SessionRepository, UserRepository
from app.services.auth import (
    AuthService,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
    LoginThrottle,
    LoginThrottledError,
    PasswordPolicyError,
    RegistrationDisabledError,
    normalize_email,
    validate_email,
    validate_password_strength,
)

GOOD_PASSWORD = "Gold2026pass"


@pytest.fixture
def fast_bcrypt(monkeypatch):
    """把 bcrypt cost 降到 4，避免整套测试被哈希成本拖成分钟级。

    默认 cost=12 的行为由 :func:`test_default_bcrypt_cost_is_12` 直接断言配置值
    （不哈希），既验证了策略又没有耗时代价。
    """
    monkeypatch.setattr(get_settings(), "bcrypt_cost", 4)


@pytest.fixture(autouse=True)
def _allow_registration(monkeypatch):
    """默认放开自助注册；单个用例可再 monkeypatch 覆盖。"""
    monkeypatch.setattr(get_settings(), "allow_registration", True)


def _service(session, *, throttle: LoginThrottle | None = None) -> AuthService:
    return AuthService(
        UserRepository(session),
        SessionRepository(session),
        get_settings(),
        throttle=throttle,
    )


class _FakeClock:
    """可控单调时钟（节流器注入用），避免测试真的 sleep。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ───────────────────── 配置与密码哈希 ─────────────────────


def test_default_bcrypt_cost_is_12() -> None:
    """路线图 V0.75.0 明确要求 bcrypt cost=12（抗离线爆破的基线）。"""
    assert get_settings().bcrypt_cost == 12


def test_hash_password_uses_bcrypt_with_configured_cost(fast_bcrypt) -> None:
    svc = _service(None)
    hashed = svc.hash_password(GOOD_PASSWORD)
    assert hashed.startswith("$2b$04$")  # fast_bcrypt 注入的 cost=4
    assert GOOD_PASSWORD not in hashed  # 明文绝不落库


def test_hash_password_contains_no_plaintext_for_default_cost() -> None:
    """cost=12 的前缀形态（只哈希一次，成本可接受）。"""
    svc = _service(None)
    hashed = svc.hash_password(GOOD_PASSWORD)
    assert hashed.startswith("$2b$12$")


def test_verify_password_roundtrip(fast_bcrypt) -> None:
    svc = _service(None)
    hashed = svc.hash_password(GOOD_PASSWORD)
    assert svc.verify_password(GOOD_PASSWORD, hashed) is True
    assert svc.verify_password("WrongPassword1", hashed) is False


def test_verify_password_tolerates_corrupt_hash() -> None:
    """哈希列被手工改坏时应返回 False（判为不匹配），而不是抛 500。"""
    svc = _service(None)
    assert svc.verify_password(GOOD_PASSWORD, "not-a-bcrypt-hash") is False


def test_verify_password_rejects_overlong_input(fast_bcrypt) -> None:
    """>72 字节的输入直接判否，避免 bcrypt 静默截断后产生「意外的等价密码」。"""
    svc = _service(None)
    hashed = svc.hash_password(GOOD_PASSWORD)
    assert svc.verify_password("x" * 80, hashed) is False


# ───────────────────── 密码策略 / 邮箱校验 ─────────────────────


@pytest.mark.parametrize(
    "bad",
    ["short1", "", "12345678", "123456789", "password", "Password1", "admin123", "  "],
)
def test_password_policy_rejects(bad: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_strength(bad)


def test_password_policy_rejects_over_72_utf8_bytes() -> None:
    """中文 3 字节/字：25 个汉字 = 75 字节 > 72 → 必须显式报错而非截断。"""
    with pytest.raises(PasswordPolicyError) as err:
        validate_password_strength("密" * 25 + "a1")
    assert "72" in str(err.value)


def test_password_policy_accepts_boundary() -> None:
    validate_password_strength("a1" + "b" * 6)  # 8 位
    validate_password_strength("x" * 70 + "y1")  # 72 字节英文字符


@pytest.mark.parametrize(
    "good",
    ["Gold2026pass", "买金1234abc", "  withspace1  "],
)
def test_password_policy_accepts(good: str) -> None:
    validate_password_strength(good)


@pytest.mark.parametrize("bad", ["", "noat", "a@b", "a b@c.com", "@x.com", "x@.com"])
def test_validate_email_rejects(bad: str) -> None:
    with pytest.raises(InvalidEmailError):
        validate_email(bad)


def test_normalize_email_lowercases_and_strips() -> None:
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_validate_email_normalizes() -> None:
    assert validate_email("  Bob@Example.com ") == "bob@example.com"


# ───────────────────── 注册 ─────────────────────


async def test_register_first_user_becomes_owner(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    user = await svc.register(email="Alice@Example.com", password=GOOD_PASSWORD)
    assert user.role == ROLE_OWNER
    assert user.email == "alice@example.com"  # 已规范化
    assert user.display_name == "alice"  # 未传显示名 → 取邮箱前缀
    assert user.is_active is True
    assert user.password_hash.startswith("$2b$")


async def test_register_second_user_is_member(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    second = await svc.register(email="b@example.com", password=GOOD_PASSWORD, display_name="小明")
    assert second.role == ROLE_MEMBER
    assert second.display_name == "小明"


async def test_register_duplicate_email_raises(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    with pytest.raises(EmailTakenError):
        await svc.register(email="A@Example.com", password=GOOD_PASSWORD)  # 大小写不同


async def test_register_disabled_when_users_exist(db_session, fast_bcrypt, monkeypatch) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    monkeypatch.setattr(get_settings(), "allow_registration", False)
    with pytest.raises(RegistrationDisabledError):
        await svc.register(email="b@example.com", password=GOOD_PASSWORD)


async def test_first_user_bypasses_registration_disabled(
    db_session, fast_bcrypt, monkeypatch
) -> None:
    """库中无用户时即使关闭自助注册也必须能建号，否则陷入「没人能建号」死锁。"""
    monkeypatch.setattr(get_settings(), "allow_registration", False)
    svc = _service(db_session)
    user = await svc.register(email="owner@example.com", password=GOOD_PASSWORD)
    assert user.role == ROLE_OWNER


async def test_register_rejects_weak_password(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    with pytest.raises(PasswordPolicyError):
        await svc.register(email="a@example.com", password="12345678")


# ───────────────────── 登录 ─────────────────────


async def test_login_success_issues_session_and_updates_last_login(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    assert user.last_login_at is None

    logged_in, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD, ip="1.2.3.4")

    assert logged_in.id == user.id
    assert len(issued.session_id) == 43  # token_urlsafe(32) → 43 字符
    assert issued.expires_at > utcnow()
    assert (await _service(db_session).authenticate(issued.session_id)).id == user.id

    refreshed = await UserRepository(db_session).get_by_id(user.id)
    assert refreshed.last_login_at is not None


async def test_login_accepts_email_case_insensitively(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    user, _ = await svc.login(email="  A@EXAMPLE.com  ", password=GOOD_PASSWORD)
    assert user.email == "a@example.com"


async def test_login_wrong_password(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    with pytest.raises(InvalidCredentialsError):
        await svc.login(email="a@example.com", password="WrongPassword9")


async def test_login_unknown_account_uses_same_message(db_session, fast_bcrypt) -> None:
    """账号不存在与密码错误必须给出**完全一致**的文案，防账号枚举。"""
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)

    with pytest.raises(InvalidCredentialsError) as wrong_pwd:
        await svc.login(email="a@example.com", password="WrongPassword9")
    with pytest.raises(InvalidCredentialsError) as no_such:
        await svc.login(email="nobody@example.com", password=GOOD_PASSWORD)

    assert str(wrong_pwd.value) == str(no_such.value)


async def test_login_disabled_account_masked_as_invalid_credentials(
    db_session, fast_bcrypt
) -> None:
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    await UserRepository(db_session).set_active(user, is_active=False)
    with pytest.raises(InvalidCredentialsError):
        await svc.login(email="a@example.com", password=GOOD_PASSWORD)


# ───────────────────── 登录节流 ─────────────────────


def _throttle(clock: _FakeClock, *, max_attempts: int = 3, lockout: int = 600) -> LoginThrottle:
    return LoginThrottle(
        max_attempts=max_attempts,
        window_seconds=900,
        lockout_seconds=lockout,
        clock=clock,
    )


async def test_login_locks_after_max_attempts(db_session, fast_bcrypt) -> None:
    clock = _FakeClock()
    svc = _service(db_session, throttle=_throttle(clock))
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)

    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            await svc.login(email="a@example.com", password="WrongPassword9", ip="9.9.9.9")

    # 第 4 次即使密码正确也拒绝（锁定期内不校验密码）
    with pytest.raises(LoginThrottledError):
        await svc.login(email="a@example.com", password=GOOD_PASSWORD, ip="9.9.9.9")


async def test_lockout_expires(db_session, fast_bcrypt) -> None:
    clock = _FakeClock()
    svc = _service(db_session, throttle=_throttle(clock, max_attempts=2, lockout=600))
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)

    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await svc.login(email="a@example.com", password="WrongPassword9", ip="9.9.9.9")
    with pytest.raises(LoginThrottledError):
        await svc.login(email="a@example.com", password=GOOD_PASSWORD, ip="9.9.9.9")

    clock.advance(601)  # 锁定到期
    user, _ = await svc.login(email="a@example.com", password=GOOD_PASSWORD, ip="9.9.9.9")
    assert user.email == "a@example.com"


async def test_successful_login_resets_failure_counter(db_session, fast_bcrypt) -> None:
    clock = _FakeClock()
    svc = _service(db_session, throttle=_throttle(clock, max_attempts=3))
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)

    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await svc.login(email="a@example.com", password="WrongPassword9", ip="9.9.9.9")
    await svc.login(email="a@example.com", password=GOOD_PASSWORD, ip="9.9.9.9")

    # 计数已清零：再失败 2 次仍不应锁定
    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await svc.login(email="a@example.com", password="WrongPassword9", ip="9.9.9.9")


def test_throttle_counts_ip_dimension_independently() -> None:
    """撞库横扫（同 IP 打多个账号）必须被 IP 维度拦下。"""
    clock = _FakeClock()
    throttle = _throttle(clock, max_attempts=2)
    throttle.record_failure("user:a@x.com", "ip:1.1.1.1")
    throttle.record_failure("user:b@x.com", "ip:1.1.1.1")
    assert throttle.check("user:c@x.com", "ip:1.1.1.1") > 0
    assert throttle.check("user:c@x.com", "ip:2.2.2.2") == 0


# ───────────────────── 会话校验 ─────────────────────


async def test_authenticate_rejects_unknown_session(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    assert await svc.authenticate(None) is None
    assert await svc.authenticate("not-a-real-session") is None


async def test_authenticate_rejects_expired_session(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    # 手工把过期时间挪到过去（模拟 14 天后的绝对过期）
    sessions = SessionRepository(db_session)
    row = await sessions.get(issued.session_id)
    row.expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    assert await svc.authenticate(issued.session_id) is None


async def test_authenticate_rejects_revoked_session(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    assert await svc.logout(issued.session_id) is True
    assert await svc.authenticate(issued.session_id) is None
    # 登出幂等：再次登出返回 False 而非抛错
    assert await svc.logout(issued.session_id) is False


async def test_authenticate_rejects_disabled_user(db_session, fast_bcrypt) -> None:
    """用户被禁用后，既有会话立即失效（禁用即止血）。"""
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)
    assert await svc.authenticate(issued.session_id) is not None

    await UserRepository(db_session).set_active(user, is_active=False)
    assert await svc.authenticate(issued.session_id) is None


async def test_authenticate_skips_touch_within_throttle_window(
    db_session, fast_bcrypt, monkeypatch
) -> None:
    """last_seen_at 节流：刚刷新过的会话再认证时**不应**产生 UPDATE。

    用 spy 包住仓储的 touch 计数——直接比较读回值会被 SQLAlchemy 的
    identity map 掩盖（同一对象，前后必然相等），断言会永真。
    """
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    sessions = SessionRepository(db_session)
    await sessions.touch(issued.session_id, utcnow())  # 刚刚刷新过

    calls: list[str] = []
    original = SessionRepository.touch

    async def spy(self, session_id, when):  # 测试替身：签名需与 SessionRepository.touch 匹配
        calls.append(session_id)
        return await original(self, session_id, when)

    monkeypatch.setattr(SessionRepository, "touch", spy)
    assert await svc.authenticate(issued.session_id) is not None
    assert calls == []


async def test_authenticate_touches_when_stale(db_session, fast_bcrypt, monkeypatch) -> None:
    """超过节流间隔后应刷新 last_seen_at（设备活跃度审计要能跟上）。"""
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, issued = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    sessions = SessionRepository(db_session)
    stale = utcnow() - timedelta(seconds=int(get_settings().session_touch_seconds) + 60)
    await sessions.touch(issued.session_id, stale)

    calls: list[str] = []
    original = SessionRepository.touch

    async def spy(self, session_id, when):  # 测试替身：签名需与 SessionRepository.touch 匹配
        calls.append(session_id)
        return await original(self, session_id, when)

    monkeypatch.setattr(SessionRepository, "touch", spy)
    assert await svc.authenticate(issued.session_id) is not None
    assert calls == [issued.session_id]


# ───────────────────── logout_all / 改密 ─────────────────────


async def test_logout_all_can_keep_current_session(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, s1 = await svc.login(email="a@example.com", password=GOOD_PASSWORD, user_agent="phone")
    _, s2 = await svc.login(email="a@example.com", password=GOOD_PASSWORD, user_agent="laptop")

    revoked = await svc.logout_all(1, keep_session_id=s2.session_id)
    assert revoked == 1
    assert await svc.authenticate(s1.session_id) is None
    assert await svc.authenticate(s2.session_id) is not None


async def test_change_password_kicks_other_devices_keeps_current(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    _, s1 = await svc.login(email="a@example.com", password=GOOD_PASSWORD)
    _, s2 = await svc.login(email="a@example.com", password=GOOD_PASSWORD)

    revoked = await svc.change_password(
        user,
        current_password=GOOD_PASSWORD,
        new_password="NewGold2026",
        keep_session_id=s2.session_id,
    )
    assert revoked == 1
    assert await svc.authenticate(s1.session_id) is None
    assert await svc.authenticate(s2.session_id) is not None

    # 新密码可登录；旧密码不再有效
    await svc.login(email="a@example.com", password="NewGold2026")
    with pytest.raises(InvalidCredentialsError):
        await svc.login(email="a@example.com", password=GOOD_PASSWORD)


async def test_change_password_requires_correct_current(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    with pytest.raises(InvalidCredentialsError):
        await svc.change_password(
            user, current_password="WrongPassword9", new_password="NewGold2026"
        )


async def test_change_password_enforces_policy(db_session, fast_bcrypt) -> None:
    svc = _service(db_session)
    user = await svc.register(email="a@example.com", password=GOOD_PASSWORD)
    with pytest.raises(PasswordPolicyError):
        await svc.change_password(user, current_password=GOOD_PASSWORD, new_password="12345678")


# ───────────────────── 仓储：唯一索引兜底 ─────────────────────


async def test_unique_email_index_blocks_direct_duplicate_insert(db_session, fast_bcrypt) -> None:
    """绕过服务层直接插重复邮箱时，唯一索引必须拦下（并发注册的最后防线）。"""
    from app.repositories.user import DuplicateEmailError

    repo = UserRepository(db_session)
    await repo.create(email="dup@example.com", password_hash="x", display_name="a")
    with pytest.raises(DuplicateEmailError):
        await repo.create(email="dup@example.com", password_hash="y", display_name="b")


async def test_users_table_starts_empty(db_session) -> None:
    """单用户模式（AUTH_ENABLED=false）下不 seed 任何用户行。"""
    assert await UserRepository(db_session).count() == 0
