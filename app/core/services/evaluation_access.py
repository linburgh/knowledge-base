from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.db import platform_role as platform_role_db
from app.db.base import DB


async def require_super_admin(current_user: CurrentUser) -> None:
    roles = await platform_role_db.get_user(DB.get(), int(current_user.user_id))
    if not any(
        role.get("code") == "p_super_admin" and role.get("status") == "active" for role in roles
    ):
        raise BusiException("无权操作自主评测", status_code=403)
