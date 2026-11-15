"""비밀번호 해시, 로그인 쿠키 서명, 세션 문자열 암호화."""

from __future__ import annotations

import base64
import hashlib
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE_NAME = "chatdb_session"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _derive(secret: str, purpose: str) -> bytes:
    return hashlib.sha256(f"chatdb:{purpose}:{secret}".encode()).digest()


class Secrets:
    """비밀 키 하나에서 용도별 키를 파생해 쓴다."""

    def __init__(self, secret_key: str, max_age_seconds: int) -> None:
        self._serializer = URLSafeTimedSerializer(
            _derive(secret_key, "cookie").hex(), salt="chatdb-session"
        )
        self._fernet = Fernet(base64.urlsafe_b64encode(_derive(secret_key, "session-store")))
        self.max_age_seconds = max_age_seconds

    # --- 로그인 쿠키 -----------------------------------------------------

    def issue_token(self, token_version: int) -> str:
        return self._serializer.dumps({"v": token_version})

    def read_token(self, token: str) -> int | None:
        """유효하면 token_version 을, 아니면 None 을 돌려준다."""
        try:
            data = self._serializer.loads(token, max_age=self.max_age_seconds)
        except BadSignature:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("v"), int):
            return None
        return data["v"]

    # --- 저장용 암호화 ---------------------------------------------------

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str | None:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, ValueError):
            return None


class LoginThrottle:
    """로그인 실패 횟수 제한. 같은 IP 에서 window 초 안에 limit 번 틀리면 잠근다."""

    def __init__(self, limit: int = 5, window: int = 900) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """잠겨 있으면 남은 초, 아니면 0."""
        now = time.monotonic()
        q = self._prune(key, now)
        if len(q) < self.limit:
            return 0
        return max(1, int(self.window - (now - q[0])))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def mask_phone(phone: str | None) -> str | None:
    """번호 가운데를 가린다. '+821012343421' → '+82 10-••••-3421'."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 7:
        return "•" * len(digits)
    tail = digits[-4:]
    if digits.startswith("82") and len(digits) >= 11:
        return f"+82 {digits[2:4]}-••••-{tail}"
    head = digits[: max(1, len(digits) - 8)]
    return f"+{head} ••••-{tail}"
