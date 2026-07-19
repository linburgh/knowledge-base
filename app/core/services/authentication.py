from __future__ import annotations

from typing import Any

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import login_log as login_log_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB


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
            raise BusiException("账号或密码错误", status_code=401)

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
        user = await user_db.get(db, id=user["id"])

    token, expires_in = auth.issue_token(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _safe_user(user),
    }


__all__ = ("login",)
