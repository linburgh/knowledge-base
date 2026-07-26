"""Shared HTTP dependencies for route-level authentication and authorization."""

from fastapi import Depends

from app.core.common import auth
from app.core.services.evaluation_access import require_super_admin


async def require_platform_super_admin(
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> auth.CurrentUser:
    await require_super_admin(current_user)
    return current_user


__all__ = ("require_platform_super_admin",)
