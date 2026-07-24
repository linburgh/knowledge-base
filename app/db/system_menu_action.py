from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db.models import RoleMenu, RoleMenuAction, SystemMenu, SystemMenuAction


def _role_conditions(table: sa.Table, role_pairs: list[tuple[str, str]]) -> list[Any]:
    return [
        sa.and_(table.c.role_scope == scope, table.c.role_code == role_code)
        for scope, role_code in role_pairs
    ]


def _base_query(role_pairs: list[tuple[str, str]]) -> sa.sql.Select:
    action_conditions = _role_conditions(RoleMenuAction, role_pairs)
    menu_conditions = _role_conditions(RoleMenu, role_pairs)
    menu_sort_order = SystemMenu.c.sort_order.label("menu_sort_order")
    action_sort_order = SystemMenuAction.c.sort_order.label("action_sort_order")
    return (
        sa.select(
            SystemMenu.c.id.label("menu_id"),
            SystemMenu.c.code.label("menu_code"),
            SystemMenu.c.name.label("menu_name"),
            SystemMenu.c.route_path,
            menu_sort_order,
            SystemMenuAction.c.id.label("action_id"),
            SystemMenuAction.c.code.label("action_code"),
            SystemMenuAction.c.name.label("action_name"),
            SystemMenuAction.c.action_type,
            action_sort_order,
        )
        .select_from(
            SystemMenuAction.join(
                SystemMenu,
                SystemMenu.c.id == SystemMenuAction.c.menu_id,
            )
            .join(
                RoleMenuAction,
                RoleMenuAction.c.action_id == SystemMenuAction.c.id,
            )
            .join(RoleMenu, RoleMenu.c.menu_id == SystemMenu.c.id)
        )
        .where(
            sa.or_(*action_conditions),
            sa.or_(*menu_conditions),
            SystemMenu.c.menu_type == "item",
            SystemMenu.c.status == "active",
            SystemMenuAction.c.status == "active",
            RoleMenuAction.c.status == "active",
            RoleMenu.c.status == "active",
        )
        .distinct()
        .order_by(
            menu_sort_order.asc(),
            SystemMenu.c.id.asc(),
            action_sort_order.asc(),
            SystemMenuAction.c.id.asc(),
        )
    )


async def list_for_roles(
    db,
    role_pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    if not role_pairs:
        return []
    rows = await db.fetch_all(_base_query(role_pairs))
    return [dict(row) for row in rows]


async def exists_for_roles(
    db,
    role_pairs: list[tuple[str, str]],
    action_code: str,
) -> bool:
    if not role_pairs:
        return False
    query = _base_query(role_pairs).where(SystemMenuAction.c.code == action_code).limit(1)
    return await db.fetch_one(query) is not None


__all__ = ("exists_for_roles", "list_for_roles")
