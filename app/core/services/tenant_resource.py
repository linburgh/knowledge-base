from __future__ import annotations

from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import knowledge_base as knowledge_base_db
from app.db import organization as organization_db
from app.db import tenant as tenant_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord


async def _require_tenant(db, tenant_id: int) -> None:
    tenant = await tenant_db.get(db, id=tenant_id)
    if tenant is None or tenant.get("status") == "deleted":
        raise BusiException("租户不存在", status_code=404)


def _validate_page(page: int, page_size: int) -> None:
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")


@check_db_connected
async def organization_candidates(
    tenant_id: int, keyword: str | None, page: int, page_size: int
) -> PageRecord:
    _validate_page(page, page_size)
    db = DB.get()
    await _require_tenant(db, tenant_id)
    return await organization_db.page_unbound(
        db, tenant_id, page, page_size, common_utils.normalize_optional_filter(keyword)
    )


@check_db_connected
async def knowledge_base_candidates(
    tenant_id: int, keyword: str | None, page: int, page_size: int
) -> PageRecord:
    _validate_page(page, page_size)
    db = DB.get()
    await _require_tenant(db, tenant_id)
    return await knowledge_base_db.page_unbound(
        db, tenant_id, page, page_size, common_utils.normalize_optional_filter(keyword)
    )


@check_db_connected
async def bind_organizations(tenant_id: int, resource_ids: list[int]) -> list[dict[str, Any]]:
    db = DB.get()
    async with db.transaction():
        await _require_tenant(db, tenant_id)
        rows = await db.fetch_all(
            organization_db.Organization.select()
            .where(organization_db.Organization.c.id.in_(resource_ids))
        )
        if len(rows) != len(set(resource_ids)):
            raise BusiException("存在不存在的组织")
        await organization_db.bind_tenant(db, resource_ids, tenant_id)
        await audit_service.record(
            db, action="bind_tenant_organizations", target_type="tenant", target_id=tenant_id,
            summary={"organization_ids": resource_ids},
        )
        return [dict(row) for row in await db.fetch_all(
            organization_db.Organization.select().where(
                organization_db.Organization.c.id.in_(resource_ids)
            )
        )]


@check_db_connected
async def bind_knowledge_bases(tenant_id: int, resource_ids: list[int]) -> list[dict[str, Any]]:
    db = DB.get()
    async with db.transaction():
        await _require_tenant(db, tenant_id)
        rows = await db.fetch_all(
            knowledge_base_db.KnowledgeBase.select().where(
                knowledge_base_db.KnowledgeBase.c.id.in_(resource_ids)
            )
        )
        if len(rows) != len(set(resource_ids)):
            raise BusiException("存在不存在的知识库")
        await knowledge_base_db.bind_tenant(db, resource_ids, tenant_id)
        await audit_service.record(
            db, action="bind_tenant_knowledge_bases", target_type="tenant", target_id=tenant_id,
            summary={"knowledge_base_ids": resource_ids},
        )
        return [dict(row) for row in await db.fetch_all(
            knowledge_base_db.KnowledgeBase.select().where(
                knowledge_base_db.KnowledgeBase.c.id.in_(resource_ids)
            )
        )]


__all__ = (
    "organization_candidates",
    "knowledge_base_candidates",
    "bind_organizations",
    "bind_knowledge_bases",
)
