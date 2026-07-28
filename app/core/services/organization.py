from __future__ import annotations

import re
from typing import Any

from app.core.common import form_limits
from app.core.common import utils as common_utils
from app.core.common import validation as common_validation
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import organization as organization_db
from app.db import platform_role as platform_role_db
from app.db import tenant as tenant_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.schemas.organization import OrganizationDto, OrganizationMemberDto
from app.schemas.organization_member import OrganizationMemberBatchItem
from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"
VALID_STATUSES = {STATUS_ACTIVE, STATUS_DISABLED, STATUS_DELETED}
MEMBER_ACTIVE = "active"
MEMBER_DISABLED = "disabled"
MEMBER_LEFT = "left"
VALID_MEMBER_STATUSES = {MEMBER_ACTIVE, MEMBER_DISABLED, MEMBER_LEFT}
VALID_ROLES = {"org_admin", "org_member"}
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate(dto: OrganizationDto, *, creating: bool = False) -> None:
    if dto is None:
        raise BusiException("组织参数不能为空")
    if creating and not dto.tenant_id:
        raise BusiException("tenant_id 不能为空")
    if dto.tenant_id is not None and dto.tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    common_validation.validate_identifier(dto.code, "code", max_length=form_limits.CODE, required=creating)
    if dto.code is not None and not CODE_PATTERN.fullmatch(dto.code):
        raise BusiException("code 只能包含小写字母、数字、下划线和短横线")
    common_validation.validate_text(
        dto.name, "name", max_length=form_limits.RESOURCE_NAME, required=creating, forbid_path=True
    )
    if dto.status is not None and dto.status not in VALID_STATUSES:
        raise BusiException("status 不合法")


def validate_member(dto: OrganizationMemberDto, *, creating: bool = False) -> None:
    if dto is None:
        raise BusiException("组织成员参数不能为空")
    if creating and not dto.user_id:
        raise BusiException("user_id 不能为空")
    if dto.user_id is not None and dto.user_id <= 0:
        raise BusiException("user_id 必须大于 0")
    if dto.role_code is not None and dto.role_code not in VALID_ROLES:
        raise BusiException("role_code 不合法")
    if dto.status is not None and dto.status not in VALID_MEMBER_STATUSES:
        raise BusiException("成员 status 不合法")


async def _require_tenant(db, tenant_id: int) -> dict[str, Any]:
    tenant = await tenant_db.get(db, id=tenant_id)
    if tenant is None or tenant.get("status") == "deleted":
        raise BusiException("租户不存在", status_code=404)
    return tenant


async def _require_user(db, user_id: int) -> dict[str, Any]:
    user = await user_db.get(db, id=user_id)
    if user is None or user.get("status") == "deleted":
        raise BusiException("用户不存在", status_code=404)
    return user


async def _ensure_admin_available(
    db, organization_id: int, *, exclude_member_id: int | None = None
) -> None:
    if await organization_db.get_active_admin(db, organization_id, exclude_member_id):
        raise BusiException("一个组织只能有一个有效的组织管理员", status_code=409)


async def _validate_parent(
    db,
    tenant_id: int,
    organization_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return
    if organization_id is not None and parent_id == organization_id:
        raise BusiException("组织不能将自身设置为父组织")
    parent = await organization_db.get(db, id=parent_id)
    if parent is None or parent.get("tenant_id") != tenant_id:
        raise BusiException("父组织不存在或不属于当前租户", status_code=400)
    if parent.get("status") == STATUS_DELETED:
        raise BusiException("父组织已删除")

    visited: set[int] = set()
    current_id = parent_id
    while current_id is not None:
        if current_id in visited:
            raise BusiException("组织层级存在循环引用")
        visited.add(current_id)
        current = await organization_db.get(db, id=current_id)
        if current is None:
            break
        current_id = current.get("parent_id")
        if organization_id is not None and current_id == organization_id:
            raise BusiException("不能将组织移动到自己的子组织下")


async def _validate_leader(db, tenant_id: int, leader_user_id: int | None) -> None:
    if leader_user_id is None:
        return
    await _require_user(db, leader_user_id)
    member = await organization_db.get_tenant_member(db, tenant_id, leader_user_id)
    if member is None:
        raise BusiException("负责人必须是当前租户的有效成员")


def _tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: dict[int, dict[str, Any]] = {}
    for row in rows:
        node = dict(row)
        node["children"] = []
        nodes[node["id"]] = node
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent_id = node.get("parent_id")
        parent = nodes.get(parent_id)
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


@check_db_connected
async def add(dto: OrganizationDto) -> dict[str, Any]:
    validate(dto, creating=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("status", STATUS_ACTIVE)
    db = DB.get()
    async with db.transaction():
        await _require_tenant(db, dto.tenant_id)
        await _validate_parent(db, dto.tenant_id, None, dto.parent_id)
        await _validate_leader(db, dto.tenant_id, dto.leader_user_id)
        try:
            organization_id = await organization_db.insert_(db, **values)
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise BusiException("当前租户下组织编码已存在", status_code=409) from exc
            raise
        organization = await organization_db.get(db, id=organization_id)
        await audit_service.record(
            db, action="create_organization", target_type="organization", target_id=organization_id,
            summary={"after": organization},
        )
    if organization is None:
        raise BusiException("组织创建失败")
    organization["member_count"] = 0
    return organization


@check_db_connected
async def modify(organization_id: int, dto: OrganizationDto) -> dict[str, Any]:
    if not organization_id:
        raise BusiException("organization_id 不能为空")
    validate(dto)
    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")
    values.pop("tenant_id", None)
    values.pop("code", None)
    db = DB.get()
    async with db.transaction():
        old = await organization_db.get(db, id=organization_id)
        if old is None:
            raise BusiException("组织不存在", status_code=404)
        if "parent_id" in values:
            await _validate_parent(db, old["tenant_id"], organization_id, values["parent_id"])
        if "leader_user_id" in values:
            await _validate_leader(db, old["tenant_id"], values["leader_user_id"])
        values["updated_at"] = common_utils.utc_now()
        await organization_db.update_(db, values, id=organization_id)
        organization = await organization_db.get(db, id=organization_id)
        await audit_service.record(
            db, action="update_organization", target_type="organization", target_id=organization_id,
            summary={"changed_fields": list(values), "after": organization},
        )
    return organization


@check_db_connected
async def remove(organization_id: int) -> dict[str, Any]:
    if not organization_id:
        raise BusiException("organization_id 不能为空")
    db = DB.get()
    async with db.transaction():
        organization = await organization_db.get(db, id=organization_id)
        await audit_service.record(
            db, action="delete_organization", target_type="organization", target_id=organization_id,
            summary={"before": organization},
        )
        if organization is None:
            raise BusiException("组织不存在", status_code=404)
        if await organization_db.count_children(db, organization["tenant_id"], organization_id):
            raise BusiException("请先删除或调整子组织")
        await organization_db.update_(
            db,
            {"status": STATUS_DELETED, "updated_at": common_utils.utc_now()},
            id=organization_id,
        )
        await organization_db.update_member(
            db,
            {"status": MEMBER_LEFT, "updated_at": common_utils.utc_now()},
            organization_id=organization_id,
        )
        organization = await organization_db.get(db, id=organization_id)
    return organization


@check_db_connected
async def get(organization_id: int) -> dict[str, Any]:
    if not organization_id:
        raise BusiException("organization_id 不能为空")
    organization = await organization_db.get(DB.get(), id=organization_id)
    if organization is None:
        raise BusiException("组织不存在", status_code=404)
    return organization


@check_db_connected
async def tree(
    current_user: CurrentUser,
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if tenant_id is not None and tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if status is not None and status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    db = DB.get()
    platform_roles = await platform_role_db.get_user(db, int(current_user.user_id))
    is_platform_super_admin = any(
        role.get("code") == PLATFORM_ROLE_SUPER_ADMIN and role.get("status") == STATUS_ACTIVE
        for role in platform_roles
    )
    if not is_platform_super_admin:
        if tenant_id is None:
            tenant_id = current_user.tenant_id
        if tenant_id is None or tenant_id != current_user.tenant_id:
            raise BusiException("只能查询当前租户的组织", status_code=403)
    elif tenant_id is not None:
        await _require_tenant(db, tenant_id)
    return _tree(await organization_db.list(db, tenant_id, keyword, status))


@check_db_connected
async def page(
    current_user: CurrentUser,
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if tenant_id is not None and tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    if status is not None and status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    db = DB.get()
    platform_roles = await platform_role_db.get_user(db, int(current_user.user_id))
    is_platform_super_admin = any(
        role.get("code") == PLATFORM_ROLE_SUPER_ADMIN and role.get("status") == STATUS_ACTIVE
        for role in platform_roles
    )
    if not is_platform_super_admin:
        if tenant_id is None:
            tenant_id = current_user.tenant_id
        if tenant_id is None or tenant_id != current_user.tenant_id:
            raise BusiException("只能查询当前租户的组织", status_code=403)
    elif tenant_id is not None:
        await _require_tenant(db, tenant_id)
    return await organization_db.page(
        db,
        page=page,
        page_size=page_size,
        tenant_id=tenant_id,
        keyword=common_utils.normalize_optional_filter(keyword),
        status=status,
    )


@check_db_connected
async def add_member(organization_id: int, dto: OrganizationMemberDto) -> dict[str, Any]:
    validate_member(dto, creating=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("role_code", "org_member")
    values.setdefault("status", MEMBER_ACTIVE)
    db = DB.get()
    async with db.transaction():
        organization = await organization_db.get(db, id=organization_id)
        if organization is None or organization.get("status") == STATUS_DELETED:
            raise BusiException("组织不存在", status_code=404)
        await _require_user(db, dto.user_id)
        if (
            await organization_db.get_tenant_member(
                db,
                organization["tenant_id"],
                dto.user_id,
            )
            is None
        ):
            raise BusiException("用户必须先加入当前租户")
        if await organization_db.get_member(
            db,
            organization_id=organization_id,
            user_id=dto.user_id,
        ):
            raise BusiException("用户已经是该组织成员", status_code=409)
        if values.get("role_code") == "org_admin" and values.get("status") == MEMBER_ACTIVE:
            await _ensure_admin_available(db, organization_id)
        try:
            member_id = await organization_db.insert_member(
                db,
                organization_id=organization_id,
                **values,
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise BusiException("用户已经是该组织成员", status_code=409) from exc
            raise
        member = await organization_db.get_member(db, id=member_id)
        await audit_service.record(
            db,
            action="add_organization_member",
            target_type="organization_member",
            target_id=member_id,
            summary={"organization_id": organization_id, "after": member},
        )
    return member


@check_db_connected
async def modify_member(member_id: int, dto: OrganizationMemberDto) -> dict[str, Any]:
    if not member_id:
        raise BusiException("member_id 不能为空")
    validate_member(dto)
    values = common_utils.clear_field_nv(dto)
    values.pop("organization_id", None)
    values.pop("user_id", None)
    if not values:
        raise BusiException("修改内容不能为空")
    db = DB.get()
    async with db.transaction():
        old = await organization_db.get_member(db, id=member_id)
        if old is None:
            raise BusiException("组织成员不存在", status_code=404)
        next_role = values.get("role_code", old.get("role_code"))
        next_status = values.get("status", old.get("status"))
        if next_role == "org_admin" and next_status == MEMBER_ACTIVE:
            await _ensure_admin_available(db, old["organization_id"], exclude_member_id=member_id)
        elif old.get("role_code") == "org_admin" and old.get("status") == MEMBER_ACTIVE:
            if await organization_db.get_active_admin(
                db, old["organization_id"], exclude_member_id=member_id
            ) is None:
                raise BusiException("一个组织必须保留一个有效的组织管理员", status_code=409)
        values["updated_at"] = common_utils.utc_now()
        await organization_db.update_member(db, values, id=member_id)
        member = await organization_db.get_member(db, id=member_id)
        await audit_service.record(
            db,
            action="update_organization_member",
            target_type="organization_member",
            target_id=member_id,
            summary={"changed_fields": list(values), "after": member},
        )
    return member


@check_db_connected
async def remove_member(member_id: int) -> dict[str, Any]:
    if not member_id:
        raise BusiException("member_id 不能为空")
    db = DB.get()
    async with db.transaction():
        old = await organization_db.get_member(db, id=member_id)
        if old is None:
            raise BusiException("组织成员不存在", status_code=404)
        if old.get("role_code") == "org_admin" and old.get("status") == MEMBER_ACTIVE:
            if await organization_db.get_active_admin(
                db, old["organization_id"], exclude_member_id=member_id
            ) is None:
                raise BusiException("一个组织必须保留一个有效的组织管理员", status_code=409)
        await organization_db.update_member(
            db,
            {"status": MEMBER_LEFT, "updated_at": common_utils.utc_now()},
            id=member_id,
        )
        member = await organization_db.get_member(db, id=member_id)
        await audit_service.record(
            db,
            action="remove_organization_member",
            target_type="organization_member",
            target_id=member_id,
            summary={"before": member},
        )
    return member


@check_db_connected
async def member_page(
    organization_id: int,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    if status is not None and status not in VALID_MEMBER_STATUSES:
        raise BusiException("成员 status 不合法")
    if await organization_db.get(DB.get(), id=organization_id) is None:
        raise BusiException("组织不存在", status_code=404)
    return await organization_db.member_page(
        DB.get(), organization_id, page, page_size, keyword, status
    )


@check_db_connected
async def member_candidates(
    organization_id: int,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    if organization_id <= 0:
        raise BusiException("organization_id 必须大于 0")
    db = DB.get()
    organization = await organization_db.get(db, id=organization_id)
    if organization is None or organization.get("status") == STATUS_DELETED:
        raise BusiException("组织不存在", status_code=404)
    return await organization_db.list_member_candidates(
        db,
        organization_id,
        organization["tenant_id"],
        common_utils.normalize_optional_filter(keyword),
    )


@check_db_connected
async def member_candidate_page(
    organization_id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if organization_id <= 0:
        raise BusiException("organization_id 必须大于 0")
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    db = DB.get()
    organization = await organization_db.get(db, id=organization_id)
    if organization is None or organization.get("status") == STATUS_DELETED:
        raise BusiException("组织不存在", status_code=404)
    return await organization_db.page_member_candidates(
        db,
        organization_id,
        organization["tenant_id"],
        page,
        page_size,
        common_utils.normalize_optional_filter(keyword),
    )


@check_db_connected
async def batch_members(
    organization_id: int,
    members: list[OrganizationMemberBatchItem],
) -> list[dict[str, Any]]:
    if organization_id <= 0:
        raise BusiException("organization_id 必须大于 0")
    user_ids = [item.user_id for item in members]
    if len(user_ids) != len(set(user_ids)):
        raise BusiException("批量成员中不能包含重复用户")
    db = DB.get()
    async with db.transaction():
        organization = await organization_db.get(db, id=organization_id)
        if organization is None or organization.get("status") == STATUS_DELETED:
            raise BusiException("组织不存在", status_code=404)
        changed: list[dict[str, Any]] = []
        for item in members:
            validate_member(
                OrganizationMemberDto(
                    user_id=item.user_id,
                    role_code=item.role_code,
                    status=item.status,
                    is_primary=item.is_primary,
                ),
                creating=True,
            )
            await _require_user(db, item.user_id)
            if await organization_db.get_tenant_member(
                db, organization["tenant_id"], item.user_id
            ) is None:
                raise BusiException(f"用户 {item.user_id} 必须先加入当前租户")
            values = {
                "role_code": item.role_code,
                "is_primary": item.is_primary,
                "status": item.status,
                "updated_at": common_utils.utc_now(),
            }
            old = await organization_db.get_member(
                db, organization_id=organization_id, user_id=item.user_id
            )
            if item.role_code == "org_admin" and item.status == MEMBER_ACTIVE:
                await _ensure_admin_available(
                    db, organization_id, exclude_member_id=old.get("id") if old else None
                )
            elif old and old.get("role_code") == "org_admin" and old.get("status") == MEMBER_ACTIVE:
                if await organization_db.get_active_admin(
                    db, organization_id, exclude_member_id=old["id"]
                ) is None:
                    raise BusiException("一个组织必须保留一个有效的组织管理员", status_code=409)
            if old is None:
                member_id = await organization_db.insert_member(
                    db,
                    organization_id=organization_id,
                    user_id=item.user_id,
                    joined_at=common_utils.utc_now(),
                    **values,
                )
            else:
                member_id = old["id"]
                await organization_db.update_member(db, values, id=member_id)
            member = await organization_db.get_member(db, id=member_id)
            changed.append(member)
        await audit_service.record(
            db,
            action="batch_update_organization_members",
            target_type="organization",
            target_id=organization_id,
            summary={"member_ids": [member["id"] for member in changed]},
        )
    return changed


__all__ = (
    "validate",
    "validate_member",
    "add",
    "modify",
    "remove",
    "get",
    "tree",
    "add_member",
    "modify_member",
    "remove_member",
    "member_page",
    "member_candidates",
    "member_candidate_page",
    "batch_members",
)
