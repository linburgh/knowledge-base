from __future__ import annotations

from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import tenant as tenant_db
from app.db import tenant_member as tenant_member_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.schemas.tenant_member import TENANT_MEMBER_STATUSES, TENANT_ROLES


def _validate_role(role_code: str | None) -> None:
    if role_code is not None and role_code not in TENANT_ROLES:
        raise BusiException("租户角色不合法")


def _validate_status(status: str | None) -> None:
    if status is not None and status not in TENANT_MEMBER_STATUSES:
        raise BusiException("租户成员状态不合法")


async def _require_tenant(db, tenant_id: int) -> dict[str, Any]:
    tenant = await tenant_db.get(db, id=tenant_id)
    if tenant is None or tenant.get("status") == "deleted":
        raise BusiException("租户不存在", status_code=404)
    return tenant


@check_db_connected
async def page(
    tenant_id: int,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    role_code: str | None = None,
) -> PageRecord:
    if tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if page <= 0 or page_size <= 0 or page_size > 100:
        raise BusiException("分页参数不合法")
    _validate_status(status)
    _validate_role(role_code)
    db = DB.get()
    await _require_tenant(db, tenant_id)
    return await tenant_member_db.page(
        db,
        tenant_id,
        page,
        page_size,
        common_utils.normalize_optional_filter(keyword),
        status,
        role_code,
    )


@check_db_connected
async def add(tenant_id: int, values: dict[str, Any]) -> dict[str, Any]:
    _validate_role(values.get("role_code"))
    _validate_status(values.get("status"))
    db = DB.get()
    async with db.transaction():
        await _require_tenant(db, tenant_id)
        user = await user_db.get(db, id=values["user_id"])
        if user is None or user.get("status") == "deleted":
            raise BusiException("用户不存在", status_code=404)
        if await tenant_member_db.get(db, tenant_id=tenant_id, user_id=values["user_id"]):
            raise BusiException("用户已经是当前租户成员", status_code=409)
        values = {
            **values,
            "tenant_id": tenant_id,
            "joined_at": common_utils.utc_now(),
        }
        try:
            member_id = await tenant_member_db.insert_(db, **values)
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise BusiException("用户已经是当前租户成员", status_code=409) from exc
            raise
        member = await tenant_member_db.get(db, id=member_id)
        await audit_service.record(
            db,
            action="add_tenant_member",
            target_type="tenant_member",
            target_id=member_id,
            summary={"after": member},
        )
    return member


@check_db_connected
async def modify(tenant_id: int, member_id: int, values: dict[str, Any]) -> dict[str, Any]:
    if member_id <= 0:
        raise BusiException("member_id 必须大于 0")
    _validate_role(values.get("role_code"))
    _validate_status(values.get("status"))
    values = {key: value for key, value in values.items() if value is not None}
    values.pop("user_id", None)
    values.pop("tenant_id", None)
    if not values:
        raise BusiException("修改内容不能为空")
    db = DB.get()
    async with db.transaction():
        old = await tenant_member_db.get(db, id=member_id)
        if old is None:
            raise BusiException("租户成员不存在", status_code=404)
        if old.get("tenant_id") != tenant_id:
            raise BusiException("租户成员不属于当前租户", status_code=404)
        values["updated_at"] = common_utils.utc_now()
        await tenant_member_db.update_(db, values, id=member_id)
        member = await tenant_member_db.get(db, id=member_id)
        await audit_service.record(
            db,
            action="update_tenant_member",
            target_type="tenant_member",
            target_id=member_id,
            summary={"before": old, "after": member},
        )
    return member


@check_db_connected
async def remove(tenant_id: int, member_id: int) -> dict[str, Any]:
    if member_id <= 0:
        raise BusiException("member_id 必须大于 0")
    db = DB.get()
    async with db.transaction():
        old = await tenant_member_db.get(db, id=member_id)
        if old is None:
            raise BusiException("租户成员不存在", status_code=404)
        if old.get("tenant_id") != tenant_id:
            raise BusiException("租户成员不属于当前租户", status_code=404)
        await tenant_member_db.update_(
            db,
            {"status": "left", "updated_at": common_utils.utc_now()},
            id=member_id,
        )
        member = await tenant_member_db.get(db, id=member_id)
        await audit_service.record(
            db,
            action="remove_tenant_member",
            target_type="tenant_member",
            target_id=member_id,
            summary={"before": old, "after": member},
        )
    return member


@check_db_connected
async def candidates(tenant_id: int, keyword: str | None = None) -> list[dict[str, Any]]:
    db = DB.get()
    await _require_tenant(db, tenant_id)
    return await tenant_member_db.list_candidates(
        db, tenant_id, common_utils.normalize_optional_filter(keyword)
    )


__all__ = ("add", "candidates", "modify", "page", "remove")
