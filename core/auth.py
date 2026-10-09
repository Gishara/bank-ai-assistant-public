"""Hardcoded demo users and JWT handling (assignment option A).

Passwords are stored as PBKDF2 hashes even for demo users so the code path is
the same one a real user store would use.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

import jwt

from core.config import get_settings
from core.rbac import Role

_SALT = b"bank-ai-assistant-demo"


def _hash(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), _SALT, 100_000).hex()


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    display_name: str
    role: Role
    department: str

    def to_claims(self) -> dict:
        return {"sub": self.user_id, "username": self.username, "name": self.display_name,
                "role": self.role.value, "department": self.department}


# username -> (user, password hash). Demo password for all: "demo123".
_DEMO_PASSWORD = _hash("demo123")
USERS: dict[str, tuple[User, str]] = {
    "viewer": (User("U-100", "viewer", "Vimukthi (Viewer)", Role.VIEWER, "product"), _DEMO_PASSWORD),
    "analyst": (User("U-200", "analyst", "Anjali (Analyst)", Role.ANALYST, "payments"), _DEMO_PASSWORD),
    "admin": (User("U-300", "admin", "Ashan (Administrator)", Role.ADMINISTRATOR, "platform"), _DEMO_PASSWORD),
}
_BY_ID = {u.user_id: u for u, _ in USERS.values()}


class AuthError(Exception):
    pass


def authenticate(username: str, password: str) -> User:
    record = USERS.get(username)
    # Compare against a hash even for unknown users to keep timing uniform.
    expected = record[1] if record else _DEMO_PASSWORD
    ok = hmac.compare_digest(_hash(password), expected)
    if not record or not ok:
        raise AuthError("Invalid username or password")
    return record[0]


def issue_token(user: User) -> str:
    settings = get_settings()
    now = int(time.time())
    claims = user.to_claims() | {"iat": now, "exp": now + settings.jwt_ttl_minutes * 60}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> User:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc
    user = _BY_ID.get(claims.get("sub", ""))
    # The role is read from the user store, not the token, so a stale token
    # cannot carry an outdated or forged role.
    if user is None:
        raise AuthError("Unknown user")
    return user


def get_user(user_id: str) -> User | None:
    return _BY_ID.get(user_id)
