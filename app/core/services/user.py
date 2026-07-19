from __future__ import annotations

import re
from typing import Any

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.schemas.user import UserDto

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"
VALID_STATUSES = {STATUS_PENDING, STATUS_ACTIVE, STATUS_DISABLED, STATUS_DELETED}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SENSITIVE_FIELDS = {"password_hash"}


def validate(dto: UserDto, *, creating: bool = False) -> None:
    if dto is None:
        raise BusiException("用户参数不能为空")
    if creating and not dto.username:
        raise BusiException("username 不能为空")
    if dto.username is not None and not USERNAME_PATTERN.fullmatch(dto.username):
        raise BusiException("username 只能包含字母、数字、点、下划线和短横线")
    if dto.display_name is not None and not dto.display_name.strip():
        raise BusiException("display_name 不能为空")
    if dto.status is not None and dto.status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    if dto.password is not None and len(dto.password) < 8:
        raise BusiException("password 至少需要 8 个字符")


def _safe(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value for key, value in row.items() if key not in SENSITIVE_FIELDS}


def _safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_safe(row) for row in rows]


def _handle_unique_error(exc: Exception) -> None:
    message = str(exc).lower()
    if "unique" in message or "duplicate" in message:
        raise BusiException("用户名、邮箱或外部身份标识已存在", status_code=409) from exc
    raise exc


@check_db_connected
async def add(dto: UserDto) -> dict[str, Any]:
    validate(dto, creating=True)
    values = common_utils.clear_field_nv(dto)
    if dto.password is not None:
        values["password_hash"] = auth.hash_password(dto.password)
    values.pop("password", None)
    values.setdefault("display_name", dto.username)
    values.setdefault("status", STATUS_PENDING)
    db = DB.get()
    async with db.transaction():
        try:
            user_id = await user_db.insert_(db, **values)
        except Exception as exc:
            _handle_unique_error(exc)
        user = await user_db.get(db, id=user_id)
    user = _safe(user)
    if user is None:
        raise BusiException("用户创建失败")
    return user


@check_db_connected
async def modify(user_id: int, dto: UserDto) -> dict[str, Any]:
    if not user_id:
        raise BusiException("user_id 不能为空")
    validate(dto)
    values = common_utils.clear_field_nv(dto)
    if dto.password is not None:
        values["password_hash"] = auth.hash_password(dto.password)
    values.pop("password", None)
    if not values:
        raise BusiException("修改内容不能为空")
    db = DB.get()
    async with db.transaction():
        if await user_db.get(db, id=user_id) is None:
            raise BusiException("用户不存在", status_code=404)
        values["updated_at"] = common_utils.utc_now()
        try:
            await user_db.update_(db, values, id=user_id)
        except Exception as exc:
            _handle_unique_error(exc)
        user = await user_db.get(db, id=user_id)
    return _safe(user)


@check_db_connected
async def remove(user_id: int) -> dict[str, Any]:
    if not user_id:
        raise BusiException("user_id 不能为空")
    db = DB.get()
    async with db.transaction():
        if await user_db.get(db, id=user_id) is None:
            raise BusiException("用户不存在", status_code=404)
        await user_db.update_(
            db,
            {"status": STATUS_DELETED, "updated_at": common_utils.utc_now()},
            id=user_id,
        )
        user = await user_db.get(db, id=user_id)
    return _safe(user)


@check_db_connected
async def get(user_id: int) -> dict[str, Any]:
    if not user_id:
        raise BusiException("user_id 不能为空")
    user = _safe(await user_db.get_with_context(DB.get(), user_id))
    if user is None:
        raise BusiException("用户不存在", status_code=404)
    return user


def _validate_filters(
    status: str | None,
    tenant_id: int | None,
    organization_id: int | None,
) -> None:
    if status is not None and status not in VALID_STATUSES:
        raise BusiException("status 不合法")
    if tenant_id is not None and tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if organization_id is not None and organization_id <= 0:
        raise BusiException("organization_id 必须大于 0")


def _normalize_filter(value: str | None) -> str | None:
    return common_utils.normalize_optional_filter(value)


@check_db_connected
async def list(
    keyword: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    keyword = _normalize_filter(keyword)
    status = _normalize_filter(status)
    _validate_filters(status, tenant_id, organization_id)
    rows = await user_db.list(
        DB.get(),
        keyword=keyword,
        status=status,
        tenant_id=tenant_id,
        organization_id=organization_id,
    )
    return _safe_rows(rows)


@check_db_connected
async def page(
    keyword: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    keyword = _normalize_filter(keyword)
    status = _normalize_filter(status)
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    _validate_filters(status, tenant_id, organization_id)
    record = await user_db.page(
        DB.get(),
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        tenant_id=tenant_id,
        organization_id=organization_id,
    )
    record.rows = _safe_rows(record.rows)
    return record


__all__ = ("validate", "add", "modify", "remove", "get", "list", "page")
