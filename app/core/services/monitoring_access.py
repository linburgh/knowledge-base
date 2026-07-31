from __future__ import annotations

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.common.roles import is_platform_super_admin
from app.db import user as user_db
from app.db.base import DB


async def _context(current_user: CurrentUser) -> dict:
    context = await user_db.get_auth_context(
        DB.get(), int(current_user.user_id), current_user.tenant_id
    )
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)
    return context


async def require_monitoring_access(current_user: CurrentUser) -> dict:
    context = await _context(current_user)
    if not is_platform_super_admin(context) and context.get("tenant_role") != "tenant_admin":
        raise BusiException("无权操作自主监控", status_code=403)
    if not is_platform_super_admin(context) and current_user.tenant_id is None:
        raise BusiException("当前用户未选择租户", status_code=403)
    return context


async def tenant_scope(current_user: CurrentUser) -> int | None:
    context = await require_monitoring_access(current_user)
    if is_platform_super_admin(context):
        return None
    return int(current_user.tenant_id)


def scoped_kwargs(scope: int | None, tenant_field: str = "tenant_id") -> dict:
    return {} if scope is None else {tenant_field: scope}
