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


async def _ensure_admin_available(
    db, tenant_id: int, *, exclude_member_id: int | None = None
) -> None:
    if await tenant_member_db.get_active_admin(db, tenant_id, exclude_member_id):
        raise BusiException("一个租户只能有一个有效的租户管理员", status_code=409)


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
        if values.get("role_code") == "tenant_admin" and values.get("status") == "active":
            await _ensure_admin_available(db, tenant_id)
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
async def batch_add(tenant_id: int, values: dict[str, Any]) -> list[dict[str, Any]]:
    user_ids = list(dict.fromkeys(values.get("user_ids") or []))
    if not user_ids or any(user_id <= 0 for user_id in user_ids):
        raise BusiException("user_ids 必须包含有效用户 ID")
    _validate_role(values.get("role_code"))
    _validate_status(values.get("status"))
    db = DB.get()
    async with db.transaction():
        await _require_tenant(db, tenant_id)
        rows = []
        for user_id in user_ids:
            user = await user_db.get(db, id=user_id)
            if user is None or user.get("status") == "deleted":
                raise BusiException(f"用户不存在: {user_id}", status_code=404)
            if await tenant_member_db.get(db, tenant_id=tenant_id, user_id=user_id):
                raise BusiException(f"用户已经是当前租户成员: {user_id}", status_code=409)
            if (
                values.get("role_code", "tenant_member") == "tenant_admin"
                and values.get("status", "active") == "active"
            ):
                await _ensure_admin_available(db, tenant_id)
            member_id = await tenant_member_db.insert_(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                role_code=values.get("role_code", "tenant_member"),
                is_primary=values.get("is_primary", False),
                status=values.get("status", "active"),
                joined_at=common_utils.utc_now(),
            )
            member = await tenant_member_db.get(db, id=member_id)
            if member is not None:
                rows.append(member)
        await audit_service.record(
            db,
            action="batch_add_tenant_members",
            target_type="tenant",
            target_id=tenant_id,
            summary={"user_ids": user_ids, "members": rows},
        )
    return rows


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
        next_role = values.get("role_code", old.get("role_code"))
        next_status = values.get("status", old.get("status"))
        if next_role == "tenant_admin" and next_status == "active":
            await _ensure_admin_available(db, tenant_id, exclude_member_id=member_id)
        elif old.get("role_code") == "tenant_admin" and old.get("status") == "active":
            if await tenant_member_db.get_active_admin(
                db, tenant_id, exclude_member_id=member_id
            ) is None:
                raise BusiException("一个租户必须保留一个有效的租户管理员", status_code=409)
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
        if old.get("role_code") == "tenant_admin" and old.get("status") == "active":
            if await tenant_member_db.get_active_admin(
                db, tenant_id, exclude_member_id=member_id
            ) is None:
                raise BusiException("一个租户必须保留一个有效的租户管理员", status_code=409)
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


@check_db_connected
async def candidate_page(
    tenant_id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if page <= 0 or page_size <= 0 or page_size > 100:
        raise BusiException("分页参数不合法")
    db = DB.get()
    await _require_tenant(db, tenant_id)
    return await tenant_member_db.page_candidates(
        db,
        tenant_id,
        page,
        page_size,
        common_utils.normalize_optional_filter(keyword),
    )


__all__ = ("add", "batch_add", "candidate_page", "candidates", "modify", "page", "remove")
