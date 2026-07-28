"""Shared HTTP dependencies for route-level authentication and authorization."""

from fastapi import Depends

from app.core.common import auth
from app.core.common.roles import is_platform_super_admin
from app.core.common.exception import BusiException
from app.core.services.evaluation_access import require_super_admin
from app.db import user as user_db
from app.db.base import DB

current_user_dependency = Depends(auth.get_current_user)


async def require_platform_super_admin(
    current_user: auth.CurrentUser = current_user_dependency,
) -> auth.CurrentUser:
    await require_super_admin(current_user)
    return current_user


async def require_platform_management(
    current_user: auth.CurrentUser = current_user_dependency,
) -> auth.CurrentUser:
    context = await user_db.get_auth_context(
        DB.get(), int(current_user.user_id), current_user.tenant_id
    )
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)
    if not is_platform_super_admin(context) and context.get("tenant_role") != "tenant_admin":
        raise BusiException("无权访问平台管理", status_code=403)
    return current_user


__all__ = ("require_platform_management", "require_platform_super_admin")
