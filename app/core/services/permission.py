from __future__ import annotations

from typing import Any

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.db import system_menu_action as system_menu_action_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB


def _role_pairs(context: dict[str, Any]) -> list[tuple[str, str]]:
    role_pairs: list[tuple[str, str]] = []
    role_pairs.extend(
        ("platform", role["code"])
        for role in context.get("platform_roles", [])
        if role.get("code")
    )
    tenant_role = context.get("tenant_role")
    if tenant_role:
        role_pairs.append(("tenant", tenant_role))
    role_pairs.extend(
        ("organization", organization["role_code"])
        for organization in context.get("organizations", [])
        if organization.get("role_code")
    )
    return list(dict.fromkeys(role_pairs))


async def _get_context(current_user: CurrentUser) -> dict[str, Any]:
    context = await user_db.get_auth_context(
        DB.get(),
        int(current_user.user_id),
        current_user.tenant_id,
    )
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)
    return context


@check_db_connected
async def get_permissions(current_user: CurrentUser) -> dict[str, Any]:
    context = await _get_context(current_user)
    rows = await system_menu_action_db.list_for_roles(DB.get(), _role_pairs(context))
    menus: dict[int, dict[str, Any]] = {}
    action_codes: list[str] = []
    for row in rows:
        menu = menus.setdefault(
            row["menu_id"],
            {
                "id": row["menu_id"],
                "code": row["menu_code"],
                "name": row["menu_name"],
                "route_path": row["route_path"],
                "actions": [],
            },
        )
        menu["actions"].append(
            {
                "id": row["action_id"],
                "code": row["action_code"],
                "name": row["action_name"],
                "action_type": row["action_type"],
            }
        )
        action_codes.append(row["action_code"])
    return {
        "menus": list(menus.values()),
        "action_codes": list(dict.fromkeys(action_codes)),
    }


@check_db_connected
async def check_actions(
    current_user: CurrentUser,
    action_codes: list[str],
) -> dict[str, Any]:
    permissions = await get_permissions(current_user)
    allowed_codes = set(permissions["action_codes"])
    return {
        "items": [
            {"action_code": action_code, "allowed": action_code in allowed_codes}
            for action_code in action_codes
        ]
    }


@check_db_connected
async def require_action(current_user: CurrentUser, action_code: str) -> None:
    context = await _get_context(current_user)
    allowed = await system_menu_action_db.exists_for_roles(
        DB.get(),
        _role_pairs(context),
        action_code,
    )
    if not allowed:
        raise BusiException("无权执行该操作", status_code=403)


__all__ = ("check_actions", "get_permissions", "require_action")
