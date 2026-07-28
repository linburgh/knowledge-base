from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.db import platform_role as platform_role_db
from app.db import user as user_db
from app.db.base import DB
from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN


async def _roles(current_user: CurrentUser) -> list[dict]:
    return await platform_role_db.get_user(DB.get(), int(current_user.user_id))


async def _context(current_user: CurrentUser) -> dict:
    context = await user_db.get_auth_context(
        DB.get(), int(current_user.user_id), current_user.tenant_id
    )
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)
    return context


async def require_super_admin(current_user: CurrentUser) -> None:
    roles = await _roles(current_user)
    if not any(
        role.get("code") == PLATFORM_ROLE_SUPER_ADMIN and role.get("status") == "active"
        for role in roles
    ):
        raise BusiException("无权操作自主评测", status_code=403)


async def require_evaluation_access(current_user: CurrentUser) -> None:
    context = await _context(current_user)
    platform_roles = {
        role.get("code")
        for role in context.get("platform_roles", [])
        if role.get("status") == "active"
    }
    if "p_super_admin" not in platform_roles and context.get("tenant_role") != "tenant_admin":
        raise BusiException("无权操作自主评测", status_code=403)


async def tenant_scope(current_user: CurrentUser) -> int | None:
    context = await _context(current_user)
    platform_roles = {
        role.get("code")
        for role in context.get("platform_roles", [])
        if role.get("status") == "active"
    }
    if PLATFORM_ROLE_SUPER_ADMIN in platform_roles:
        return None
    if current_user.tenant_id is None:
        raise BusiException("当前用户未选择租户", status_code=403)
    return int(current_user.tenant_id)
