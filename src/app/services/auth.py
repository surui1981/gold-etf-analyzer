"""认证服务（V0.75.0 认证骨架）。

职责边界
--------
- **密码**：策略校验 + bcrypt(cost=12) 哈希 / 校验；明文只在函数栈上存在，
  不进日志、不落库、不进异常信息。
- **注册**：邮箱规范化（strip + lower）+ 唯一性（唯一索引兜底）+ 首个用户成为 owner。
- **登录**：失败原因**对外统一**（不区分「无此账号 / 密码错 / 已禁用」），
  防止账号枚举；配合进程内节流器抵御在线暴力破解。
- **会话**：签发不透明随机 ID、校验（撤销 / 过期 / 用户禁用三重判定）、
  登出撤销、改密后批量踢出。

安全设计要点
------------
1. **bcrypt 72 字节上限**：bcrypt 只取前 72 字节，超出部分被静默忽略。
   这里**显式拒绝** >72 字节的密码（而非悄悄截断），避免「用户以为设了长密码、
   实际后半段无效」的隐蔽陷阱。注意按 **UTF-8 字节**计算，中文密码 24 个汉字即触顶。
2. **未知账号也跑一次 bcrypt**：否则「立即返回」与「校验失败」的耗时差
   会成为账号枚举侧信道。用惰性预计算的哑元哈希打平耗时。
3. **throttle 是进程内状态**：与 ``middleware/rate_limit.py`` 同思路。
   单进程部署下有效；多副本部署需换成 Redis 等共享存储（当前架构为单机，够用）。
   key 同时按「账号」与「IP」双维度计数 —— 前者防定点爆破，后者防撞库横扫。
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import bcrypt

from app.config import Settings, get_settings
from app.models.user import (
    DEFAULT_SESSION_TTL_HOURS,
    ROLE_MEMBER,
    ROLE_OWNER,
    User,
    UserSession,
    as_naive_utc,
    utcnow,
)
from app.repositories.user import DuplicateEmailError, SessionRepository, UserRepository
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 密码长度：下限 8（NIST 最小建议量级）、上限 72 **字节**（bcrypt 硬限制）
PASSWORD_MIN_LENGTH = 8
BCRYPT_MAX_BYTES = 72

# 常见弱口令黑名单（小样本，只为拦住最离谱的几条；真正的防线是长度 + 锁定）
_WEAK_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty123",
        "admin123",
        "letmein1",
        "iloveyou",
        "welcome1",
        "abc12345",
        "11111111",
    }
)

# 邮箱格式：刻意宽松（只拦明显非邮箱的串），真正的有效性由「能否收到邮件」决定
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MAX_EMAIL_LENGTH = 255
MAX_DISPLAY_NAME_LENGTH = 64
MAX_USER_AGENT_LENGTH = 256

# 会话 ID 熵：token_urlsafe(32) = 32 字节 = 256 bit ≈ 43 字符
SESSION_ID_BYTES = 32


class AuthError(Exception):
    """认证 / 账号相关业务错误基类。

    ``code`` 供前端做分支（如 ``password_weak`` → 高亮密码框），
    ``message`` 是**可直接展示给用户的中文文案**。
    """

    code = "auth_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidCredentialsError(AuthError):
    """账号或密码不正确（不区分具体原因）。"""

    code = "invalid_credentials"


class AccountDisabledError(AuthError):
    """账号已被禁用。

    ⚠ 注意：**登录路径不抛此异常**（统一成 :class:`InvalidCredentialsError`，
    避免泄露「该账号存在但被禁用」）；它只在「已登录后被禁用」时由中间件使用。
    """

    code = "account_disabled"


class RegistrationDisabledError(AuthError):
    """管理员关闭了自助注册。"""

    code = "registration_disabled"


class EmailTakenError(AuthError):
    """该邮箱已注册。"""

    code = "email_taken"


class PasswordPolicyError(AuthError):
    """密码不满足策略（过短 / 过长 / 过弱）。"""

    code = "password_weak"


class LoginThrottledError(AuthError):
    """登录失败次数过多，暂时锁定。"""

    code = "login_throttled"


class InvalidEmailError(AuthError):
    """邮箱格式非法。"""

    code = "email_invalid"


@dataclass(frozen=True)
class IssuedSession:
    """签发结果：cookie 值 + 过期时间（端点据此设置 Set-Cookie）。"""

    session_id: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    """邮箱规范化：去空白 + 转小写。

    小写化是**唯一索引能真正防重**的前提（``Alice@x.com`` 与 ``alice@x.com``
    必须是同一账号，否则用户会「注册成功却登不上」）。
    """
    return (email or "").strip().lower()


def validate_password_strength(password: str) -> None:
    """校验密码策略；不满足则抛 :class:`PasswordPolicyError`。

    策略：8 字符起、UTF-8 ≤ 72 字节、非纯数字、不在弱口令黑名单。
    """
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"密码至少 {PASSWORD_MIN_LENGTH} 位")
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise PasswordPolicyError(
            f"密码过长（按 UTF-8 计算不得超过 {BCRYPT_MAX_BYTES} 字节，"
            "约 24 个汉字或 72 个英文字符）"
        )
    if password.isdigit():
        raise PasswordPolicyError("密码不能是纯数字")
    if password.strip().lower() in _WEAK_PASSWORDS:
        raise PasswordPolicyError("密码过于常见，请更换")


def validate_email(email: str) -> str:
    """校验并返回规范化邮箱；非法则抛 :class:`InvalidEmailError`。"""
    normalized = normalize_email(email)
    if not normalized or len(normalized) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(normalized):
        raise InvalidEmailError("邮箱格式不正确")
    return normalized


class LoginThrottle:
    """进程内登录失败节流器（滑动窗口 + 锁定）。

    维度：``user:<email>`` 与 ``ip:<ip>`` 各自独立计数，**任一命中即拒绝**。
    - 成功登录清空该维度计数；
    - 解锁时间过后自动清理旧时间戳（惰性清理，无需后台任务）。
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        lockout_seconds: int,
        clock=time.monotonic,
    ) -> None:
        self._max = max(1, max_attempts)
        self._window = max(1, window_seconds)
        self._lockout = max(1, lockout_seconds)
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, *keys: str) -> int:
        """返回剩余锁定时长（秒）；0 表示未锁定。"""
        now = self._clock()
        with self._lock:
            remaining = 0.0
            for key in keys:
                until = self._locked_until.get(key, 0.0)
                if until > now:
                    remaining = max(remaining, until - now)
            return int(remaining) + (1 if remaining else 0)

    def record_failure(self, *keys: str) -> None:
        """记录一次失败；达阈值即锁定。"""
        now = self._clock()
        with self._lock:
            for key in keys:
                stamps = [t for t in self._hits.get(key, []) if now - t < self._window]
                stamps.append(now)
                if len(stamps) >= self._max:
                    self._locked_until[key] = now + self._lockout
                    self._hits[key] = []
                else:
                    self._hits[key] = stamps

    def reset(self, *keys: str) -> None:
        """登录成功后清空计数与锁定。"""
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)
                self._locked_until.pop(key, None)


# 惰性哑元哈希：未知账号时也跑一次同代价 bcrypt，打平耗时侧信道。
_DUMMY_HASH: bytes | None = None
_DUMMY_LOCK = threading.Lock()


def _dummy_hash(cost: int) -> bytes:
    """返回并缓存一个同代价的哑元哈希（首次调用付一次哈希成本）。"""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        with _DUMMY_LOCK:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = bcrypt.hashpw(b"pm-dummy-password", bcrypt.gensalt(cost))
    return _DUMMY_HASH


class AuthService:
    """注册 / 登录 / 会话 编排服务。"""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        settings: Settings | None = None,
        throttle: LoginThrottle | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._settings = settings or get_settings()
        if throttle is None:
            throttle = LoginThrottle(
                max_attempts=self._settings.login_max_attempts,
                window_seconds=self._settings.login_attempt_window_minutes * 60,
                lockout_seconds=self._settings.login_lockout_minutes * 60,
            )
        self._throttle = throttle

    # ─────────────── 密码 ───────────────

    def hash_password(self, password: str) -> str:
        """bcrypt 哈希（cost 由 ``BCRYPT_COST`` 控制，默认 12）。"""
        validate_password_strength(password)
        cost = int(self._settings.bcrypt_cost)
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(cost)).decode("ascii")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """校验密码；哈希格式损坏时返回 False（而非抛错，避免 500 泄露内部状态）。"""
        if not password or len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
            return False
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
        except (ValueError, TypeError):
            logger.warning("verify_password: 哈希格式非法，判定为不匹配")
            return False

    # ─────────────── 注册 ───────────────

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
    ) -> User:
        """注册新用户。

        - 库中无任何用户时**无视** ``ALLOW_REGISTRATION``，首个注册者成为 owner
          （否则会陷入「没人能建号」的死锁）。
        - 其余情况下若关闭了自助注册，抛 :class:`RegistrationDisabledError`。

        Raises:
            InvalidEmailError: 邮箱格式非法
            PasswordPolicyError: 密码不满足策略
            RegistrationDisabledError: 已关闭自助注册且库中已有用户
            EmailTakenError: 邮箱已被注册
        """
        normalized = validate_email(email)
        validate_password_strength(password)

        existing_count = await self._users.count()
        if existing_count > 0 and not self._settings.allow_registration:
            raise RegistrationDisabledError("管理员已关闭自助注册，请联系管理员开通账号")

        role = ROLE_OWNER if existing_count == 0 else ROLE_MEMBER
        name = (display_name or "").strip()[:MAX_DISPLAY_NAME_LENGTH]

        try:
            user = await self._users.create(
                email=normalized,
                password_hash=self.hash_password(password),
                display_name=name,
                role=role,
            )
        except DuplicateEmailError as exc:
            raise EmailTakenError("该邮箱已注册，请直接登录") from exc

        logger.info("auth: 注册成功 user_id=%s role=%s", user.id, user.role)
        return user

    # ─────────────── 登录 / 会话 ───────────────

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[User, IssuedSession]:
        """校验凭据并签发会话。

        Raises:
            LoginThrottledError: 失败次数过多被锁定（此时**不校验密码**，避免白跑 bcrypt）
            InvalidCredentialsError: 账号或密码不正确 / 账号被禁用（统一文案）
        """
        normalized = normalize_email(email)
        throttle_keys = (f"user:{normalized}", f"ip:{ip or '-'}")

        locked = self._throttle.check(*throttle_keys)
        if locked:
            logger.warning("auth: 登录被节流 email=%s ip=%s 剩余=%ss", normalized, ip, locked)
            raise LoginThrottledError(f"登录失败次数过多，请 {max(1, locked // 60)} 分钟后再试")

        user = await self._users.get_by_email(normalized) if normalized else None

        if user is None:
            # 打平耗时：未知账号也跑一次 bcrypt，避免「响应快 = 账号不存在」侧信道
            bcrypt.checkpw(
                password.encode("utf-8")[:BCRYPT_MAX_BYTES],
                _dummy_hash(int(self._settings.bcrypt_cost)),
            )
            self._throttle.record_failure(*throttle_keys)
            logger.info("auth: 登录失败（账号不存在）email=%s ip=%s", normalized, ip)
            raise InvalidCredentialsError("账号或密码不正确")

        if not self.verify_password(password, user.password_hash):
            self._throttle.record_failure(*throttle_keys)
            logger.info("auth: 登录失败（密码错误）user_id=%s ip=%s", user.id, ip)
            raise InvalidCredentialsError("账号或密码不正确")

        if not user.is_active:
            # 文案与「密码错」完全一致：不泄露「该账号存在但被禁用」
            self._throttle.record_failure(*throttle_keys)
            logger.warning("auth: 登录失败（账号已禁用）user_id=%s ip=%s", user.id, ip)
            raise InvalidCredentialsError("账号或密码不正确")

        self._throttle.reset(*throttle_keys)
        issued = await self._issue_session(user, user_agent=user_agent, ip=ip)
        await self._users.mark_login(user, utcnow())
        logger.info("auth: 登录成功 user_id=%s ip=%s", user.id, ip)
        return user, issued

    async def _issue_session(
        self,
        user: User,
        *,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        """签发一条会话（随机 ID + 绝对过期时间）。"""
        ttl_hours = int(self._settings.session_ttl_hours) or DEFAULT_SESSION_TTL_HOURS
        session_id = secrets.token_urlsafe(SESSION_ID_BYTES)
        expires_at = utcnow() + timedelta(hours=ttl_hours)
        await self._sessions.create(
            session_id=session_id,
            user_id=user.id,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:MAX_USER_AGENT_LENGTH] or None,
            ip=(ip or "")[:64] or None,
        )
        return IssuedSession(session_id=session_id, expires_at=expires_at)

    async def authenticate(self, session_id: str | None) -> User | None:
        """把 cookie 里的会话 ID 解析为用户；任一步不满足即返回 None。

        判定链：会话存在 → 未撤销 → 未过期 → 用户存在 → 用户启用。
        副作用：按 ``SESSION_TOUCH_SECONDS`` 节流地刷新 ``last_seen_at``。
        """
        if not session_id:
            return None
        row: UserSession | None = await self._sessions.get(session_id)
        if row is None or not row.is_live:
            return None

        user = await self._users.get_by_id(row.user_id)
        if user is None or not user.is_active:
            return None

        await self._touch_if_stale(row)
        return user

    async def _touch_if_stale(self, row: UserSession) -> None:
        """按节流间隔刷新 ``last_seen_at``；失败只告警，不影响本次认证。"""
        threshold = int(self._settings.session_touch_seconds)
        now = utcnow()
        if threshold > 0 and row.last_seen_at is not None:
            last_seen = as_naive_utc(row.last_seen_at)
            if last_seen is not None and (now - last_seen).total_seconds() < threshold:
                return
        try:
            await self._sessions.touch(row.id, now)
        except Exception:  # 审计字段，写失败不该让请求 500
            logger.warning("auth: 刷新 last_seen_at 失败 session=%s…", row.id[:8])

    async def logout(self, session_id: str | None) -> bool:
        """撤销单个会话；返回是否确实撤销了。"""
        if not session_id:
            return False
        row = await self._sessions.get(session_id)
        if row is None or row.revoked_at is not None:
            return False
        await self._sessions.revoke(session_id, utcnow())
        return True

    async def logout_all(self, user_id: int, *, keep_session_id: str | None = None) -> int:
        """撤销某用户全部会话，返回被踢下线的会话数。"""
        return await self._sessions.revoke_all_for_user(
            user_id, utcnow(), except_session_id=keep_session_id
        )

    async def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
        keep_session_id: str | None = None,
    ) -> int:
        """改密并踢出其他设备，返回被踢下线的会话数。

        改密后**保留当前设备**登录（``keep_session_id``），其余会话全部撤销 ——
        这既符合用户预期，也让「密码泄露后改密」真正能止血。

        Raises:
            InvalidCredentialsError: 当前密码不正确
            PasswordPolicyError: 新密码不满足策略
        """
        if not self.verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("当前密码不正确")
        validate_password_strength(new_password)
        await self._users.update_password_hash(user, self.hash_password(new_password))
        revoked = await self.logout_all(user.id, keep_session_id=keep_session_id)
        logger.info("auth: 改密成功 user_id=%s 踢出会话数=%s", user.id, revoked)
        return revoked


__all__ = [
    "AccountDisabledError",
    "AuthError",
    "AuthService",
    "EmailTakenError",
    "InvalidCredentialsError",
    "InvalidEmailError",
    "IssuedSession",
    "LoginThrottle",
    "LoginThrottledError",
    "PasswordPolicyError",
    "RegistrationDisabledError",
    "normalize_email",
    "validate_email",
    "validate_password_strength",
]
