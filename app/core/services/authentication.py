from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import auth_session as auth_session_db
from app.db import login_log as login_log_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB


def _session_expiry(ttl_seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=ttl_seconds)


async def _issue_sessions(
    db,
    user_id: int,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    access_token, expires_in = auth.issue_token(user_id)
    refresh_token, refresh_expires_in = auth.issue_token(
        user_id,
        ttl_seconds=auth.REFRESH_TOKEN_TTL_SECONDS,
        token_type="refresh",
    )
    access = auth.parse_token(access_token)
    refresh = auth.parse_token(refresh_token)
    await auth_session_db.insert_(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        jti=access.jti,
        token_type="access",
        expires_at=_session_expiry(expires_in),
    )
    await auth_session_db.insert_(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        jti=refresh.jti,
        token_type="refresh",
        expires_at=_session_expiry(refresh_expires_in),
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
    }


def _safe_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in user.items()
        if key not in {"password_hash", "external_subject"}
    }


@check_db_connected
async def login(
    account: str,
    password: str,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    db = DB.get()
    user = await user_db.get_by_account(db, account)
    failure_reason = None
    tokens: dict[str, Any] | None = None
    if user is None:
        failure_reason = "invalid_credentials"
    elif user.get("status") in {"pending", "disabled", "deleted"}:
        failure_reason = f"account_{user.get('status')}"
    elif not auth.verify_password(password, user.get("password_hash")):
        failure_reason = "invalid_credentials"

    async with db.transaction():
        if failure_reason is not None:
            await login_log_db.insert_(
                db,
                user_id=user.get("id") if user else None,
                login_account=account,
                login_type="password",
                result="failed",
                failure_reason=failure_reason,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
            )
            await audit_service.record(
                db,
                action="login",
                target_type="user",
                target_id=user.get("id") if user else None,
                result="failure",
                error_message=failure_reason,
                summary={"account": account},
            )
        else:
            now = common_utils.utc_now()
            await user_db.update_(db, {"last_login_at": now, "updated_at": now}, id=user["id"])
            await login_log_db.insert_(
                db,
                user_id=user["id"],
                login_account=account,
                login_type="password",
                result="success",
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
            )
            await audit_service.record(
                db,
                action="login",
                target_type="user",
                target_id=user["id"],
                summary={"account": account},
            )

            user = await user_db.get(db, id=user["id"])
            context = await user_db.get_auth_context(db, user["id"])
            tenant = context["current_tenant"] if context else None
            tokens = await _issue_sessions(
                db,
                user["id"],
                tenant["id"] if tenant else None,
            )

    if failure_reason is not None:
        raise BusiException("账号或密码错误", status_code=401)

    assert tokens is not None
    return {**tokens, "user": _safe_user(user)}


@check_db_connected
async def me(current_user: CurrentUser) -> dict[str, Any]:
    try:
        user_id = int(current_user.user_id)
    except ValueError:
        raise BusiException("当前用户无效", status_code=401) from None
    context = await user_db.get_auth_context(DB.get(), user_id, current_user.tenant_id)
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)
    context["user"] = _safe_user(context["user"])
    return context


@check_db_connected
async def tenants(current_user: CurrentUser) -> list[dict[str, Any]]:
    context = await user_db.get_auth_context(DB.get(), int(current_user.user_id))
    if context is None:
        raise BusiException("用户不存在或已失效", status_code=401)
    return context["tenants"]


@check_db_connected
async def select_tenant(current_user: CurrentUser, tenant_id: int) -> dict[str, Any]:
    if tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    db = DB.get()
    context = await user_db.get_auth_context(db, int(current_user.user_id))
    if context is None:
        raise BusiException("用户不存在或已失效", status_code=401)
    tenant = next((item for item in context["tenants"] if item["id"] == tenant_id), None)
    if tenant is None:
        raise BusiException("无权访问该租户", status_code=403)
    async with db.transaction():
        await auth_session_db.update_tenant_for_user(db, current_user.user_id, tenant_id)
        await audit_service.record(
            db,
            action="select_tenant",
            target_type="tenant",
            target_id=tenant_id,
            summary={"user_id": current_user.user_id},
        )
    selected_user = CurrentUser(
        user_id=current_user.user_id,
        token=current_user.token,
        jti=current_user.jti,
        tenant_id=tenant_id,
        token_type=current_user.token_type,
    )
    return await me(selected_user)


@check_db_connected
async def refresh(refresh_token: str) -> dict[str, Any]:
    current_user = auth.parse_token(refresh_token)
    if current_user.token_type != "refresh" or not current_user.jti:
        raise BusiException("Refresh Token 无效", status_code=401)
    db = DB.get()
    session = await auth_session_db.get_active(db, current_user.jti, "refresh")
    if session is None or str(session.get("user_id")) != current_user.user_id:
        raise BusiException("Refresh Token 已失效", status_code=401)
    user = await user_db.get(db, id=int(current_user.user_id))
    if user is None or user.get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)

    async with db.transaction():
        now = common_utils.utc_now()
        await auth_session_db.revoke(db, current_user.jti, revoked_at=now)
        tokens = await _issue_sessions(
            db,
            int(current_user.user_id),
            session.get("tenant_id"),
        )
        await login_log_db.insert_(
            db,
            user_id=int(current_user.user_id),
            login_account=user.get("username", ""),
            login_type="password",
            result="refresh",
        )
        await audit_service.record(
            db,
            action="refresh_token",
            target_type="user",
            target_id=current_user.user_id,
        )
    return tokens


@check_db_connected
async def logout(current_user: CurrentUser) -> dict[str, str]:
    if not current_user.jti:
        return {"status": "logged_out"}
    db = DB.get()
    async with db.transaction():
        now = common_utils.utc_now()
        await auth_session_db.revoke_all(db, current_user.user_id, revoked_at=now)
        await login_log_db.insert_(
            db,
            user_id=int(current_user.user_id),
            login_account=current_user.user_id,
            login_type="password",
            result="logout",
        )
        await audit_service.record(
            db,
            action="logout",
            target_type="user",
            target_id=current_user.user_id,
        )
    return {"status": "logged_out"}


__all__ = ("login", "logout", "me", "refresh", "select_tenant", "tenants")
