"""Seed an isolated organization forest with 100k nodes at every level."""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime

import sqlalchemy as sa

from app.config import configure
from app.db import base as db_base
from app.db.models import Organization, Tenant

TENANT_CODE = "org-tree-perf-500k"
TENANT_NAME = "组织树分页性能测试租户"
NODES_PER_LEVEL = 100_000
LEVEL_COUNT = 11
LEVEL_NODE_COUNTS = (
    NODES_PER_LEVEL,
    NODES_PER_LEVEL,
    NODES_PER_LEVEL * 2 - 1,
    NODES_PER_LEVEL * 2 - 1,
    *(NODES_PER_LEVEL for _ in range(LEVEL_COUNT - 4)),
)
DEFAULT_NODE_COUNT = sum(LEVEL_NODE_COUNTS)
DEFAULT_TREE_COUNT = NODES_PER_LEVEL
BATCH_SIZE = 3_000


async def get_or_create_tenant(db) -> int:
    row = await db.fetch_one(sa.select(Tenant.c.id).where(Tenant.c.code == TENANT_CODE))
    if row:
        return int(row["id"])
    return int(
        await db.fetch_val(
            sa.insert(Tenant)
            .values(code=TENANT_CODE, name=TENANT_NAME, status="active")
            .returning(Tenant.c.id)
        )
    )


async def reset_tenant(db, tenant_id: int) -> None:
    await db.execute(sa.delete(Organization).where(Organization.c.tenant_id == tenant_id))


async def insert_level(
    db,
    tenant_id: int,
    level: int,
    parent_ids: dict[int, int] | None,
    timestamp: datetime,
) -> dict[int, int]:
    node_ids: dict[int, int] = {}
    level_node_count = LEVEL_NODE_COUNTS[level]
    for start in range(0, level_node_count, BATCH_SIZE):
        end = min(start + BATCH_SIZE, level_node_count)
        rows = [
            {
                "tenant_id": tenant_id,
                "parent_id": (
                    None if parent_ids is None else parent_ids[_parent_index(level, index)]
                ),
                "code": f"PERF-{index:06d}-L{level:02d}-0000",
                "name": _node_name(level, index),
                "status": "active",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            for index in range(start, end)
        ]
        query = (
            sa.insert(Organization)
            .values(rows)
            .returning(
                Organization.c.id,
                Organization.c.code,
            )
        )
        result = await db.fetch_all(query)
        for row in result:
            code = str(row["code"])
            node_ids[int(code.split("-")[1])] = int(row["id"])
    return node_ids


def _parent_index(level: int, index: int) -> int:
    if level == 1:
        return 0
    if level in (2, 3):
        if index < NODES_PER_LEVEL:
            return 0
        return index - NODES_PER_LEVEL + 1
    return index


def _node_name(level: int, index: int) -> str:
    if level == 0:
        return f"性能测试树-{index:06d}-第0级"
    if level == 1:
        if index == 0:
            return "性能测试树-000000-第1级链路"
        return f"性能测试树-000000-第1级链路-同级-{index:06d}"
    if level in (2, 3):
        if index == 0:
            return f"性能测试树-000000-第{level}级链路"
        if index < NODES_PER_LEVEL:
            return f"性能测试树-000000-第{level}级链路-同级-{index:06d}"
        parent_index = index - NODES_PER_LEVEL + 1
        return f"性能测试树-{parent_index:06d}-第{level}级链路"
    return f"性能测试树-{index:06d}-第{level}级链路"


async def seed(node_count: int, tree_count: int, reset: bool) -> tuple[int, float]:
    if node_count != DEFAULT_NODE_COUNT:
        raise ValueError(
            f"node_count 必须为 {DEFAULT_NODE_COUNT}（各级数量为 {list(LEVEL_NODE_COUNTS)}）"
        )
    if tree_count != DEFAULT_TREE_COUNT:
        raise ValueError(f"tree_count 必须为 {DEFAULT_TREE_COUNT}")

    configure("app")
    await db_base.setup()
    db = db_base.DATABASE
    assert db is not None
    timestamp = datetime.now(UTC)
    started = time.perf_counter()
    try:
        async with db.transaction():
            tenant_id = await get_or_create_tenant(db)
            if reset:
                await reset_tenant(db, tenant_id)
            parent_ids = None
            for level in range(LEVEL_COUNT):
                parent_ids = await insert_level(
                    db,
                    tenant_id,
                    level,
                    parent_ids,
                    timestamp,
                )
        elapsed = time.perf_counter() - started
        print(
            f"seeded tenant_id={tenant_id} nodes={node_count} levels={LEVEL_COUNT} "
            f"level_counts={list(LEVEL_NODE_COUNTS)} elapsed={elapsed:.2f}s"
        )
        return tenant_id, elapsed
    finally:
        await db_base.DATABASE.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-count", type=int, default=DEFAULT_NODE_COUNT)
    parser.add_argument("--tree-count", type=int, default=DEFAULT_TREE_COUNT)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    asyncio.run(seed(args.node_count, args.tree_count, args.reset))


if __name__ == "__main__":
    main()
