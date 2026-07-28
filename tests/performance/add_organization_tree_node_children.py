"""Ensure the level-8 and level-9 performance nodes have 100,000 children."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa

from app.config import configure
from app.db import base as db_base
from app.db.models import Organization, Tenant

TENANT_CODE = "org-tree-perf-500k"
BATCH_SIZE = 3_000
TARGETS = (
    *(
        {
            "name": f"性能测试树-000000-第{level}级链路",
            "child_prefix": f"性能测试树-000000-第{level + 1}级链路-同级-",
            "code_prefix": f"perf-org{level}-l{level + 1:02d}-",
            "target_count": 10_000,
        }
        for level in range(1, 8)
    ),
    {
        "name": "性能测试树-000000-第8级链路",
        "child_prefix": "性能测试树-000000-第9级链路-同级-",
        "code_prefix": "perf-org8-l09-",
        "target_count": 100_000,
    },
    {
        "name": "性能测试树-000000-第9级链路",
        "child_prefix": "性能测试树-000000-第10级链路-同级-",
        "code_prefix": "perf-org9-l10-",
        "target_count": 100_000,
    },
)


async def ensure_children() -> list[tuple[str, int, int]]:
    tenant = await db_base.DB.get().fetch_one(
        sa.select(Tenant.c.id).where(Tenant.c.code == TENANT_CODE)
    )
    if tenant is None:
        raise RuntimeError(f"测试租户不存在：{TENANT_CODE}")
    db = db_base.DB.get()
    results = []
    for target in TARGETS:
        parent = await db.fetch_one(
            sa.select(Organization.c.id).where(
                Organization.c.tenant_id == tenant["id"],
                Organization.c.name == target["name"],
                Organization.c.status != "deleted",
            )
        )
        if parent is None:
            raise RuntimeError(f"目标组织不存在：{target['name']}")
        existing = await db.fetch_all(
            sa.select(Organization.c.name).where(
                Organization.c.tenant_id == tenant["id"],
                Organization.c.parent_id == parent["id"],
                Organization.c.name.like(f"{target['child_prefix']}%"),
                Organization.c.status != "deleted",
            )
        )
        existing_names = {str(row["name"]) for row in existing}
        missing_rows = [
            {
                "tenant_id": tenant["id"],
                "parent_id": parent["id"],
                "code": f"{target['code_prefix']}{index:06d}",
                "name": f"{target['child_prefix']}{index:06d}",
                "status": "active",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            for index in range(1, target["target_count"])
            if f"{target['child_prefix']}{index:06d}" not in existing_names
        ]
        async with db.transaction():
            for start in range(0, len(missing_rows), BATCH_SIZE):
                await db.execute(
                    sa.insert(Organization).values(missing_rows[start : start + BATCH_SIZE])
                )
        total = int(
            await db.fetch_val(
                sa.select(sa.func.count()).select_from(Organization).where(
                    Organization.c.tenant_id == tenant["id"],
                    Organization.c.parent_id == parent["id"],
                    Organization.c.status != "deleted",
                )
            )
        )
        results.append((target["name"], int(parent["id"]), total))
    return results


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="./etc")
    args = parser.parse_args()
    import os

    os.environ["OS_CONFIG_DIR"] = args.config_dir
    configure("app")
    await db_base.setup()
    await db_base.inject_db()
    for target_name, parent_id, total in await ensure_children():
        print(f"target={target_name} parent_id={parent_id} direct_child_count={total}")


if __name__ == "__main__":
    asyncio.run(main())
