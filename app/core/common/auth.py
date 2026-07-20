from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Header

from app.config import CONF
from app.core.common.exception import BusiException


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    token: str | None = None
    jti: str | None = None
    tenant_id: int | None = None
    token_type: str = "access"


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


def _environment() -> str:
    try:
        return CONF.default.environment
    except AttributeError:
        return "development"


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password or not password_hash:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _token_secret() -> bytes:
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        if _environment() == "production":
            raise BusiException("生产环境必须配置 AUTH_SECRET", status_code=500)
        secret = "development-only-token-secret"
    return secret.encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(
    user_id: int,
    *,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
    token_type: str = "access",
) -> tuple[str, int]:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": secrets.token_hex(16),
        "typ": token_type,
    }
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _encode(
        hmac.new(_token_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded_payload}.{signature}", ttl_seconds


def parse_token(token: str) -> CurrentUser:
    try:
        encoded_payload, signature = token.split(".", 1)
        expected = _encode(
            hmac.new(
                _token_secret(), encoded_payload.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(_decode(encoded_payload))
        user_id = int(payload["sub"])
        jti = str(payload["jti"])
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        raise BusiException("认证 Token 无效或已过期", status_code=401) from None
    return CurrentUser(
        user_id=str(user_id),
        token=token,
        jti=jti,
        token_type=str(payload.get("typ", "access")),
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise BusiException("认证 Token 不能为空", status_code=401)
        current_user = parse_token(token)
        if current_user.token_type != "access" or not current_user.jti:
            raise BusiException("Token 类型无效", status_code=401)
        from app.db import auth_session as auth_session_db
        from app.db.base import DB, inject_db

        await inject_db()
        session = await auth_session_db.get_active(DB.get(), current_user.jti, "access")
        if session is None or str(session.get("user_id")) != current_user.user_id:
            raise BusiException("Token 已失效", status_code=401)
        return CurrentUser(
            user_id=current_user.user_id,
            token=current_user.token,
            jti=current_user.jti,
            tenant_id=session.get("tenant_id"),
            token_type=current_user.token_type,
        )

    try:
        environment = CONF.default.environment
        dev_user_id = CONF.default.dev_user_id
    except AttributeError:
        environment, dev_user_id = "development", None
    if environment == "development" and dev_user_id:
        return CurrentUser(user_id=dev_user_id)

    raise BusiException("未认证", status_code=401)


__all__ = (
    "CurrentUser",
    "get_current_user",
    "hash_password",
    "verify_password",
    "issue_token",
    "parse_token",
    "TOKEN_TTL_SECONDS",
    "REFRESH_TOKEN_TTL_SECONDS",
)
