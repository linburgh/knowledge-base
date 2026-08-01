from __future__ import annotations

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.common.roles import effective_role, is_platform_super_admin
from app.db.platform import system_menu as system_menu_db
from app.db.platform import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN


def _role_pairs(context: dict) -> list[tuple[str, str]]:
    if is_platform_super_admin(context):
        return [("platform", PLATFORM_ROLE_SUPER_ADMIN)]
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


def _default_path(context: dict, tree: list[dict]) -> str | None:
    if effective_role(context) == "tenant_guest":
        return "/guest/knowledge-bases"

    items = system_menu_db.flatten_items(tree)
    if not items:
        return None
    if is_platform_super_admin(context):
        overview = next(
            (item for item in items if item["code"] == "platform_overview"),
            None,
        )
        if overview is not None:
            return overview["route_path"]
    return items[0]["route_path"]


@check_db_connected
async def get_menus(current_user: CurrentUser) -> dict:
    context = await user_db.get_auth_context(
        DB.get(),
        int(current_user.user_id),
        current_user.tenant_id,
    )
    if context is None or context["user"].get("status") in {"disabled", "deleted"}:
        raise BusiException("用户不存在或已失效", status_code=401)

    rows = await system_menu_db.list_for_roles(DB.get(), _role_pairs(context))
    tree = system_menu_db.build_tree(rows)
    return {"default_path": _default_path(context, tree), "menus": tree}


__all__ = ("get_menus",)
