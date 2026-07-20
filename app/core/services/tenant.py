from __future__ import annotations

import re
from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import tenant as tenant_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.schemas.tenant import TenantDto

STATUS_TRIAL = "trial"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"
VALID_STATUSES = {STATUS_TRIAL, STATUS_ACTIVE, STATUS_DISABLED, STATUS_DELETED}
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate(dto: TenantDto, *, creating: bool = False) -> None:
    if dto is None:
        raise BusiException("租户参数不能为空")
    if creating and not dto.code:
        raise BusiException("code 不能为空")
    if dto.code is not None:
        if not CODE_PATTERN.fullmatch(dto.code):
            raise BusiException("code 只能包含小写字母、数字、下划线和短横线")
    if creating and not dto.name:
        raise BusiException("name 不能为空")
    if dto.name is not None and not dto.name.strip():
        raise BusiException("name 不能为空")
    if dto.status is not None and dto.status not in VALID_STATUSES:
        raise BusiException("status 不合法")


@check_db_connected
async def add(dto: TenantDto) -> dict[str, Any]:
    validate(dto, creating=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("status", STATUS_TRIAL)
    db = DB.get()
    async with db.transaction():
        try:
            tenant_id = await tenant_db.insert_(db, **values)
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise BusiException("租户编码已存在", status_code=409) from exc
            raise
        tenant = await tenant_db.get(db, id=tenant_id)
        await audit_service.record(
            db, action="create_tenant", target_type="tenant", target_id=tenant_id,
            summary={"after": tenant},
        )
    if tenant is None:
        raise BusiException("租户创建失败")
    return tenant


@check_db_connected
async def modify(tenant_id: int, dto: TenantDto) -> dict[str, Any]:
    if not tenant_id:
        raise BusiException("tenant_id 不能为空")
    validate(dto)
    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")
    db = DB.get()
    async with db.transaction():
        if await tenant_db.get(db, id=tenant_id) is None:
            raise BusiException("租户不存在", status_code=404)
        values["updated_at"] = common_utils.utc_now()
        await tenant_db.update_(db, values, id=tenant_id)
        tenant = await tenant_db.get(db, id=tenant_id)
        await audit_service.record(
            db, action="update_tenant", target_type="tenant", target_id=tenant_id,
            summary={"changed_fields": list(values), "after": tenant},
        )
    return tenant


@check_db_connected
async def remove(tenant_id: int) -> dict[str, Any]:
    if not tenant_id:
        raise BusiException("tenant_id 不能为空")
    db = DB.get()
    async with db.transaction():
        if await tenant_db.get(db, id=tenant_id) is None:
            raise BusiException("租户不存在", status_code=404)
        await tenant_db.update_(
            db,
            {"status": STATUS_DELETED, "updated_at": common_utils.utc_now()},
            id=tenant_id,
        )
        tenant = await tenant_db.get(db, id=tenant_id)
        await audit_service.record(
            db, action="delete_tenant", target_type="tenant", target_id=tenant_id,
            summary={"before": tenant},
        )
    return tenant


@check_db_connected
async def get(tenant_id: int) -> dict[str, Any]:
    if not tenant_id:
        raise BusiException("tenant_id 不能为空")
    tenant = await tenant_db.get_with_stats(DB.get(), tenant_id)
    if tenant is None:
        raise BusiException("租户不存在", status_code=404)
    return tenant


def _filters(code: str | None, status: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {"code": code}
    filters["status"] = status if status is not None else None
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    return filters


@check_db_connected
async def list(
    code: str | None = None, name: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    code = common_utils.normalize_optional_filter(code)
    name = common_utils.normalize_optional_filter(name)
    status = common_utils.normalize_optional_filter(status)
    if status is not None and status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    return await tenant_db.list(DB.get(), **_filters(code, status), name=name)


@check_db_connected
async def page(
    code: str | None = None,
    name: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    code = common_utils.normalize_optional_filter(code)
    name = common_utils.normalize_optional_filter(name)
    status = common_utils.normalize_optional_filter(status)
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    if status is not None and status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    return await tenant_db.page(
        DB.get(), page=page, page_size=page_size, **_filters(code, status), name=name
    )


__all__ = ("validate", "add", "modify", "remove", "get", "list", "page")
