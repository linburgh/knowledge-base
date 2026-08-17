"""Create an isolated ten-level organization-tree demonstration dataset."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import UTC, datetime

import sqlalchemy as sa

from app.config import configure
from app.db import base as db_base
from app.db.models import Organization, Tenant

TENANT_CODE = "infinite-tree-demo"
TENANT_NAME = "无极树演示租户"
ROOT_CODE = "infinite-tree-demo-root"
ROOT_NAME = "无极树演示节点"
MAX_DEPTH = 10
CHILDREN_PER_LEVEL = 100_000
EXPECTED_NODE_COUNT = 1 + MAX_DEPTH * CHILDREN_PER_LEVEL


def chain_code(depth: int) -> str:
    """Return the stable code of the one child that continues to the next level."""
    return f"infinite-tree-demo-l{depth:02d}-000000"


def validate_existing_count(existing_count: int) -> None:
    """Reject partial datasets so a normal rerun never mixes old and new nodes."""
    if existing_count not in (0, EXPECTED_NODE_COUNT):
        raise RuntimeError(
            "检测到不完整的无极树演示数据；请使用 --reset 重建。"
            f" expected={EXPECTED_NODE_COUNT}, actual={existing_count}"
        )


async def get_or_create_tenant(db) -> int:
    """Create the isolated demonstration tenant without touching business tenants."""
    tenant_id = await db.fetch_val(
        sa.select(Tenant.c.id).where(Tenant.c.code == TENANT_CODE)
    )
    if tenant_id is not None:
        return int(tenant_id)
    return int(
        await db.fetch_val(
            sa.insert(Tenant)
            .values(
                code=TENANT_CODE,
                name=TENANT_NAME,
                description="十级、每级十万直接子节点的组织树演示数据",
                status="active",
            )
            .returning(Tenant.c.id)
        )
    )


async def insert_root(db, tenant_id: int, timestamp: datetime) -> int:
    """Insert the uniquely named root node at depth zero."""
    return int(
        await db.fetch_val(
            sa.insert(Organization)
            .values(
                tenant_id=tenant_id,
                parent_id=None,
                code=ROOT_CODE,
                name=ROOT_NAME,
                status="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
            .returning(Organization.c.id)
        )
    )


async def insert_level(
    db,
    *,
    tenant_id: int,
    parent_id: int,
    depth: int,
    timestamp: datetime,
) -> int:
    """Insert 100k direct children and return the child that continues the main chain."""
    query = sa.text(
        """
        insert into t_organization (
            tenant_id,
            parent_id,
            code,
            name,
            status,
            created_at,
            updated_at
        )
        select
            :tenant_id,
            :parent_id,
            'infinite-tree-demo-l' || lpad(:depth_text, 2, '0') || '-' ||
                lpad(cast(series_no as text), 6, '0'),
            case
                when series_no = 0
                    then '无极树演示节点-第' || lpad(:depth_text, 2, '0') || '级链路'
                else '无极树演示节点-第' || lpad(:depth_text, 2, '0') ||
                    '级-' || lpad(cast(series_no as text), 6, '0')
            end,
            'active',
            :created_at,
            :updated_at
        from generate_series(0, :last_child_index) as generated(series_no)
        """
    ).bindparams(
        sa.bindparam("tenant_id", value=tenant_id, type_=sa.BigInteger()),
        sa.bindparam("parent_id", value=parent_id, type_=sa.BigInteger()),
        # lpad 的输入是文本，直接绑定字符串，避免 asyncpg 将 CAST 参数推断为 text
        # 后仍收到 Python int。
        sa.bindparam("depth_text", value=str(depth), type_=sa.String()),
        sa.bindparam(
            "last_child_index",
            value=CHILDREN_PER_LEVEL - 1,
            type_=sa.Integer(),
        ),
        sa.bindparam(
            "created_at",
            value=timestamp,
            type_=sa.DateTime(timezone=True),
        ),
        sa.bindparam(
            "updated_at",
            value=timestamp,
            type_=sa.DateTime(timezone=True),
        ),
    )
    # LoggingDatabase 的 TextClause 参数需要预先绑定，不能通过 execute(values=...) 注入。
    await db.execute(query)
    next_id = await db.fetch_val(
        sa.select(Organization.c.id).where(
            Organization.c.tenant_id == tenant_id,
            Organization.c.code == chain_code(depth),
        )
    )
    if next_id is None:
        raise RuntimeError(f"第 {depth} 级主链节点创建失败")
    return int(next_id)


async def load_chain_ids(db, tenant_id: int) -> list[int]:
    """Load root and depth 1-10 chain node IDs from an existing dataset."""
    codes = [ROOT_CODE, *(chain_code(depth) for depth in range(1, MAX_DEPTH + 1))]
    rows = await db.fetch_all(
        sa.select(Organization.c.id, Organization.c.code).where(
            Organization.c.tenant_id == tenant_id,
            Organization.c.code.in_(codes),
            Organization.c.status != "deleted",
        )
    )
    ids_by_code = {str(row["code"]): int(row["id"]) for row in rows}
    missing_codes = [code for code in codes if code not in ids_by_code]
    if missing_codes:
        raise RuntimeError(f"演示树数据不完整，缺少主链节点：{missing_codes}")
    return [ids_by_code[code] for code in codes]


async def verify(db, tenant_id: int, chain_ids: list[int]) -> None:
    """Verify total count, maximum depth and every main-chain child count."""
    total = int(
        await db.fetch_val(
            sa.select(sa.func.count()).select_from(Organization).where(
                Organization.c.tenant_id == tenant_id,
                Organization.c.status != "deleted",
            )
        )
    )
    if total != EXPECTED_NODE_COUNT:
        raise RuntimeError(f"节点总数错误：expected={EXPECTED_NODE_COUNT}, actual={total}")

    for depth, parent_id in enumerate(chain_ids[:-1]):
        child_count = int(
            await db.fetch_val(
                sa.select(sa.func.count()).select_from(Organization).where(
                    Organization.c.tenant_id == tenant_id,
                    Organization.c.parent_id == parent_id,
                    Organization.c.status != "deleted",
                )
            )
        )
        if child_count != CHILDREN_PER_LEVEL:
            raise RuntimeError(
                f"第 {depth} 级直接子节点数量错误："
                f"expected={CHILDREN_PER_LEVEL}, actual={child_count}"
            )

    deepest_child_count = int(
        await db.fetch_val(
            sa.select(sa.func.count()).select_from(Organization).where(
                Organization.c.tenant_id == tenant_id,
                Organization.c.parent_id == chain_ids[-1],
                Organization.c.status != "deleted",
            )
        )
    )
    if deepest_child_count != 0:
        raise RuntimeError(f"第 {MAX_DEPTH} 级不是叶子层：children={deepest_child_count}")


async def seed(*, reset: bool) -> tuple[int, float]:
    """Create or verify the complete dataset in one transaction."""
    configure("app")
    await db_base.setup()
    db = db_base.DATABASE
    assert db is not None
    started = time.perf_counter()
    try:
        async with db.transaction():
            tenant_id = await get_or_create_tenant(db)
            existing_count = int(
                await db.fetch_val(
                    sa.select(sa.func.count()).select_from(Organization).where(
                        Organization.c.tenant_id == tenant_id
                    )
                )
            )
            if reset and existing_count:
                await db.execute(
                    sa.delete(Organization).where(Organization.c.tenant_id == tenant_id)
                )
                existing_count = 0

            validate_existing_count(existing_count)
            if existing_count:
                chain_ids = await load_chain_ids(db, tenant_id)
            else:
                timestamp = datetime.now(UTC)
                root_id = await insert_root(db, tenant_id, timestamp)
                chain_ids = [root_id]
                parent_id = root_id
                for depth in range(1, MAX_DEPTH + 1):
                    parent_id = await insert_level(
                        db,
                        tenant_id=tenant_id,
                        parent_id=parent_id,
                        depth=depth,
                        timestamp=timestamp,
                    )
                    chain_ids.append(parent_id)

            await verify(db, tenant_id, chain_ids)

        elapsed = time.perf_counter() - started
        print(
            f"seeded tenant_id={tenant_id} root_name={ROOT_NAME} "
            f"max_depth={MAX_DEPTH} children_per_level={CHILDREN_PER_LEVEL} "
            f"nodes={EXPECTED_NODE_COUNT} elapsed={elapsed:.2f}s"
        )
        return tenant_id, elapsed
    finally:
        await db.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="./etc")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    os.environ["OS_CONFIG_DIR"] = args.config_dir
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
