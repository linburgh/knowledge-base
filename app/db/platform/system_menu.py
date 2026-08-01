from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db.models import RoleMenu, SystemMenu


async def list_active(db) -> list[dict[str, Any]]:
    query = (
        sa.select(SystemMenu)
        .where(SystemMenu.c.status == "active", SystemMenu.c.visible.is_(True))
        .order_by(SystemMenu.c.sort_order.asc(), SystemMenu.c.id.asc())
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def list_for_roles(
    db,
    role_pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    if not role_pairs:
        return []

    role_conditions = [
        sa.and_(RoleMenu.c.role_scope == scope, RoleMenu.c.role_code == role_code)
        for scope, role_code in role_pairs
    ]
    query = (
        sa.select(SystemMenu)
        .select_from(SystemMenu.join(RoleMenu, RoleMenu.c.menu_id == SystemMenu.c.id))
        .where(
            sa.or_(*role_conditions),
            SystemMenu.c.status == "active",
            SystemMenu.c.visible.is_(True),
            RoleMenu.c.status == "active",
        )
        .distinct()
        .order_by(SystemMenu.c.sort_order.asc(), SystemMenu.c.id.asc())
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


def build_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = {
        row["id"]: {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "menu_type": row["menu_type"],
            "route_path": row.get("route_path"),
            "icon": row.get("icon"),
            "sort_order": row.get("sort_order", 0),
            "meta": row.get("meta") or {},
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, Any]] = []
    for row in rows:
        node = nodes[row["id"]]
        parent_id = row.get("parent_id")
        if parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def flatten_items(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in tree:
        if node["menu_type"] == "item" and node.get("route_path"):
            items.append(node)
        items.extend(flatten_items(node["children"]))
    return items


__all__ = ("build_tree", "flatten_items", "list_active", "list_for_roles")
