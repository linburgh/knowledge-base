from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.config import CONF
from app.core.common import utils as common_utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import knowledge_base as knowledge_base_db
from app.db import knowledge_base_organization as knowledge_base_organization_db
from app.db import knowledge_base_prompt as knowledge_base_prompt_db
from app.db import knowledge_base_user as knowledge_base_user_db
from app.db import organization as organization_db
from app.db import platform_role as platform_role_db
from app.db import tenant as tenant_db
from app.db import tenant_member as tenant_member_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.db.models import Conversation, Document
from app.schemas.knowledge_base import KnowledgeBaseDto
from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN

STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"
DEFAULT_VISIBILITY = "private"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_RETRIEVAL_TOP_K = 5
MAX_DESCRIPTION_LENGTH = 500
MAX_SYSTEM_PROMPT_LENGTH = 10000


async def _resolve_created_by(db, owner_id: str) -> int:
    """Resolve the owner field to the numeric user ID stored in created_by."""
    user = None
    try:
        user = await user_db.get(db, id=int(owner_id))
    except (TypeError, ValueError):
        user = await user_db.get(db, username=owner_id)
    if user is None:
        raise BusiException("owner_id 对应用户不存在", status_code=404)
    return int(user["id"])


async def _resolve_tenant_scope(
    current_user: CurrentUser,
    tenant_id: int | None,
) -> int | None:
    db = DB.get()
    platform_roles = await platform_role_db.get_user(db, int(current_user.user_id))
    is_platform_super_admin = any(
        role.get("code") == PLATFORM_ROLE_SUPER_ADMIN and role.get("status") == STATUS_ACTIVE
        for role in platform_roles
    )
    if is_platform_super_admin:
        return tenant_id
    if tenant_id is None:
        return current_user.tenant_id
    if current_user.tenant_id != tenant_id:
        raise BusiException("只能查询当前租户的知识库", status_code=403)
    return tenant_id


def validate(dto: KnowledgeBaseDto) -> None:
    if dto is None:
        raise BusiException("知识库参数不能为空")
    
    if not dto.name:
        raise BusiException("name 不能为空")
    if not dto.owner_id:
        raise BusiException("owner_id 不能为空")
    if dto.tenant_id is not None and dto.tenant_id <= 0:
        raise BusiException("tenant_id 必须大于 0")
    if dto.description is not None and len(dto.description) > MAX_DESCRIPTION_LENGTH:
        raise BusiException("description 不能超过 500 个字符")
    if dto.system_prompt is not None and len(dto.system_prompt) > MAX_SYSTEM_PROMPT_LENGTH:
        raise BusiException("system_prompt 不能超过 10000 个字符")
    if dto.chunk_size is not None and dto.chunk_size <= 0:
        raise BusiException("chunk_size 必须大于 0")
    if dto.chunk_overlap is not None and dto.chunk_overlap < 0:
        raise BusiException("chunk_overlap 不能小于 0")
    if (
        dto.chunk_size is not None
        and dto.chunk_overlap is not None
        and dto.chunk_overlap >= dto.chunk_size
    ):
        raise BusiException("chunk_overlap 必须小于 chunk_size")
    if dto.retrieval_top_k is not None and dto.retrieval_top_k <= 0:
        raise BusiException("retrieval_top_k 必须大于 0")


@check_db_connected
async def add(dto: KnowledgeBaseDto) -> Any:
    rd = None

    validate(dto)
    if dto.tenant_id is None:
        raise BusiException("tenant_id 不能为空")
    
    values = common_utils.clear_field_nv(dto)
    values.setdefault("description", "")
    values.setdefault("visibility", DEFAULT_VISIBILITY)
    values.setdefault(
        "embedding_model",
        CONF.embedding.model or DEFAULT_EMBEDDING_MODEL,
    )
    values.setdefault("chunk_size", DEFAULT_CHUNK_SIZE)
    values.setdefault("chunk_overlap", DEFAULT_CHUNK_OVERLAP)
    values.setdefault("retrieval_top_k", DEFAULT_RETRIEVAL_TOP_K)
    values.setdefault("system_prompt", "")
    values.setdefault("system_prompt_version", 1)
    values.setdefault("status", STATUS_ACTIVE)

    db = DB.get()
    async with db.transaction():
        tenant = await tenant_db.get(db, id=dto.tenant_id)
        if tenant is None or tenant.get("status") == "deleted":
            raise BusiException("租户不存在", status_code=404)
        values["created_by"] = await _resolve_created_by(db, dto.owner_id)
        knowledge_base_id = await knowledge_base_db.insert_(db, **values)
        await knowledge_base_prompt_db.insert_(
            db,
            kb_id=knowledge_base_id,
            version=1,
            system_prompt=values["system_prompt"],
            created_by=dto.owner_id,
        )
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
        await audit_service.record(
            db,
            action="create_knowledge_base",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            summary={"after": rd},
        )
    if rd is None:
        raise BusiException("知识库创建失败")
    return rd


@check_db_connected
async def modify(knowledge_base_id: int, dto: KnowledgeBaseDto) -> Any:
    rd = None

    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    validate(dto)

    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")

    db = DB.get()
    async with db.transaction():
        old = await knowledge_base_db.get(db, id=knowledge_base_id)
        if old is None:
            raise BusiException("知识库不存在", status_code=404)

        values.pop("tenant_id", None)

        values["updated_at"] = common_utils.utc_now()
        if "system_prompt" in values and values["system_prompt"] != old.get("system_prompt", ""):
            values["system_prompt_version"] = int(old.get("system_prompt_version") or 1) + 1
            values["system_prompt_updated_at"] = values["updated_at"]
            await knowledge_base_prompt_db.insert_(
                db,
                kb_id=knowledge_base_id,
                version=values["system_prompt_version"],
                system_prompt=values["system_prompt"],
                created_by=await _resolve_created_by(db, dto.owner_id or old["owner_id"]),
            )
        await knowledge_base_db.update_(db, values, id=knowledge_base_id)
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
        await audit_service.record(
            db,
            action="update_knowledge_base",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            summary={"changed_fields": list(values.keys()), "before": old, "after": rd},
        )
    return rd


@check_db_connected
async def remove(knowledge_base_id: int) -> Any:
    rd = None
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")

    db = DB.get()
    async with db.transaction():
        old = await knowledge_base_db.get(db, id=knowledge_base_id)
        if old is None:
            raise BusiException("知识库不存在", status_code=404)

        document_count = int(
            await db.fetch_val(
                sa.select(sa.func.count())
                .select_from(Document)
                .where(
                    Document.c.kb_id == knowledge_base_id,
                    Document.c.status != STATUS_DELETED,
                )
            )
            or 0
        )
        conversation_count = int(
            await db.fetch_val(
                sa.select(sa.func.count())
                .select_from(Conversation)
                .where(
                    Conversation.c.kb_id == knowledge_base_id,
                    Conversation.c.status != STATUS_DELETED,
                )
            )
            or 0
        )
        if document_count or conversation_count:
            dependencies = []
            if document_count:
                dependencies.append(f"文档{document_count}条")
            if conversation_count:
                dependencies.append(f"会话{conversation_count}条")
            raise BusiException(
                "知识库仍存在未处理资源，不能删除：" + "、".join(dependencies),
                status_code=409,
            )

        await knowledge_base_db.update_(
            db,
            {
                "status": STATUS_DELETED,
                "updated_at": common_utils.utc_now(),
            },
            id=knowledge_base_id,
        )
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
        await audit_service.record(
            db,
            action="delete_knowledge_base",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            summary={"before": old, "after": rd},
        )
    return rd


@check_db_connected
async def get(id: int) -> dict[str, Any]:
    if not id:
        raise BusiException("knowledge_base_id 不能为空")

    db = DB.get()
    row = await knowledge_base_db.get(db, id=id)
    if row is None:
        raise BusiException("知识库不存在", status_code=404)
    return row


@check_db_connected
async def prompt_history(knowledge_base_id: int) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")

    db = DB.get()
    knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
    if knowledge_base is None:
        raise BusiException("知识库不存在", status_code=404)
    return await knowledge_base_prompt_db.list(db, kb_id=knowledge_base_id)


@check_db_connected
async def organization_grants(knowledge_base_id: int) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    db = DB.get()
    if await knowledge_base_db.get(db, id=knowledge_base_id) is None:
        raise BusiException("知识库不存在", status_code=404)
    return await knowledge_base_organization_db.list(db, knowledge_base_id)


@check_db_connected
async def available_organizations(
    knowledge_base_id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    db = DB.get()
    knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
    if knowledge_base is None:
        raise BusiException("知识库不存在", status_code=404)
    return await knowledge_base_organization_db.available_page(
        db,
        kb_id=knowledge_base_id,
        tenant_id=knowledge_base["tenant_id"],
        keyword=common_utils.normalize_optional_filter(keyword),
        page=page,
        page_size=page_size,
    )


@check_db_connected
async def grant_organization(
    knowledge_base_id: int, organization_id: int, created_by: int
) -> dict[str, Any]:
    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)
        organization = await organization_db.get(db, id=organization_id)
        if organization is None or organization.get("tenant_id") != knowledge_base.get("tenant_id"):
            raise BusiException("组织不存在或不属于当前租户", status_code=400)
        if await knowledge_base_organization_db.get(
            db, kb_id=knowledge_base_id, organization_id=organization_id
        ):
            raise BusiException("组织已经获得当前知识库授权", status_code=409)
        grant_id = await knowledge_base_organization_db.insert_(
            db,
            kb_id=knowledge_base_id,
            organization_id=organization_id,
            created_by=created_by,
        )
        return await knowledge_base_organization_db.get(db, id=grant_id)


@check_db_connected
async def batch_grant_organizations(
    knowledge_base_id: int,
    organization_ids: list[int],
    created_by: int,
) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    if not organization_ids:
        raise BusiException("organization_ids 不能为空")
    if any(organization_id <= 0 for organization_id in organization_ids):
        raise BusiException("organization_id 必须大于 0")
    if len(organization_ids) != len(set(organization_ids)):
        raise BusiException("organization_ids 不能包含重复组织")

    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)
        grant_ids: list[int] = []
        for organization_id in organization_ids:
            organization = await organization_db.get(db, id=organization_id)
            if (
                organization is None
                or organization.get("tenant_id") != knowledge_base.get("tenant_id")
            ):
                raise BusiException("组织不存在或不属于当前租户", status_code=400)
            if await knowledge_base_organization_db.get(
                db, kb_id=knowledge_base_id, organization_id=organization_id
            ):
                raise BusiException("组织已经获得当前知识库授权", status_code=409)
            grant_ids.append(
                await knowledge_base_organization_db.insert_(
                    db,
                    kb_id=knowledge_base_id,
                    organization_id=organization_id,
                    created_by=created_by,
                )
            )
        grants = [
            await knowledge_base_organization_db.get(db, id=grant_id)
            for grant_id in grant_ids
        ]
        await audit_service.record(
            db,
            action="batch_grant_knowledge_base_organizations",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            summary={"organization_ids": organization_ids},
        )
    return [grant for grant in grants if grant is not None]


@check_db_connected
async def revoke_organization(knowledge_base_id: int, organization_id: int) -> dict[str, Any]:
    db = DB.get()
    async with db.transaction():
        grant = await knowledge_base_organization_db.get(
            db, kb_id=knowledge_base_id, organization_id=organization_id
        )
        if grant is None:
            raise BusiException("知识库组织授权不存在", status_code=404)
        await knowledge_base_organization_db.delete_(db, id=grant["id"])
    return grant


@check_db_connected
async def user_grants(knowledge_base_id: int) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    db = DB.get()
    if await knowledge_base_db.get(db, id=knowledge_base_id) is None:
        raise BusiException("知识库不存在", status_code=404)
    return await knowledge_base_user_db.list(db, knowledge_base_id)


@check_db_connected
async def available_users(
    knowledge_base_id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > 100:
        raise BusiException("page_size 必须在 1 到 100 之间")
    db = DB.get()
    knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
    if knowledge_base is None:
        raise BusiException("知识库不存在", status_code=404)
    return await knowledge_base_user_db.available_page(
        db,
        kb_id=knowledge_base_id,
        tenant_id=knowledge_base["tenant_id"],
        keyword=common_utils.normalize_optional_filter(keyword),
        page=page,
        page_size=page_size,
    )


@check_db_connected
async def grant_user(
    knowledge_base_id: int, user_id: int, created_by: int
) -> dict[str, Any]:
    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)
        user = await user_db.get(db, id=user_id)
        if user is None or user.get("status") in {"deleted", "disabled"}:
            raise BusiException("用户不存在或已禁用", status_code=404)
        member = await tenant_member_db.get(
            db,
            tenant_id=knowledge_base["tenant_id"],
            user_id=user_id,
            status="active",
        )
        if member is None:
            raise BusiException("用户不是当前知识库所属租户的有效成员", status_code=400)
        if await knowledge_base_user_db.get(
            db, kb_id=knowledge_base_id, user_id=user_id
        ):
            raise BusiException("用户已经获得当前知识库授权", status_code=409)
        grant_id = await knowledge_base_user_db.insert_(
            db,
            kb_id=knowledge_base_id,
            user_id=user_id,
            created_by=created_by,
        )
        return await knowledge_base_user_db.get(db, id=grant_id)


@check_db_connected
async def batch_grant_users(
    knowledge_base_id: int,
    user_ids: list[int],
    created_by: int,
) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    if not user_ids:
        raise BusiException("user_ids 不能为空")
    if any(user_id <= 0 for user_id in user_ids):
        raise BusiException("user_id 必须大于 0")
    if len(user_ids) != len(set(user_ids)):
        raise BusiException("user_ids 不能包含重复用户")

    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)
        grant_ids: list[int] = []
        for user_id in user_ids:
            user = await user_db.get(db, id=user_id)
            if user is None or user.get("status") in {"deleted", "disabled"}:
                raise BusiException("用户不存在或已禁用", status_code=404)
            member = await tenant_member_db.get(
                db,
                tenant_id=knowledge_base["tenant_id"],
                user_id=user_id,
                status="active",
            )
            if member is None:
                raise BusiException("用户不是当前知识库所属租户的有效成员", status_code=400)
            if await knowledge_base_user_db.get(
                db, kb_id=knowledge_base_id, user_id=user_id
            ):
                raise BusiException("用户已经获得当前知识库授权", status_code=409)
            grant_ids.append(
                await knowledge_base_user_db.insert_(
                    db,
                    kb_id=knowledge_base_id,
                    user_id=user_id,
                    created_by=created_by,
                )
            )
        grants = [
            await knowledge_base_user_db.get(db, id=grant_id)
            for grant_id in grant_ids
        ]
        await audit_service.record(
            db,
            action="batch_grant_knowledge_base_users",
            target_type="knowledge_base",
            target_id=knowledge_base_id,
            summary={"user_ids": user_ids},
        )
    return [grant for grant in grants if grant is not None]


@check_db_connected
async def revoke_user(knowledge_base_id: int, user_id: int) -> dict[str, Any]:
    db = DB.get()
    async with db.transaction():
        grant = await knowledge_base_user_db.get(
            db, kb_id=knowledge_base_id, user_id=user_id
        )
        if grant is None:
            raise BusiException("知识库用户授权不存在", status_code=404)
        await knowledge_base_user_db.delete_(db, id=grant["id"])
    return grant


@check_db_connected
async def list(
    name: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    tenant_id: int | None = None,
    current_user: CurrentUser | None = None,
) -> list[dict[str, Any]]:
    if current_user is None:
        raise BusiException("当前用户不能为空", status_code=401)
    tenant_id = await _resolve_tenant_scope(current_user, tenant_id)
    filters: dict[str, Any] = {
        "name": common_utils.normalize_optional_filter(name),
        "owner_id": owner_id,
        "visibility": visibility,
        "tenant_id": tenant_id,
    }
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await knowledge_base_db.list(DB.get(), **filters)


@check_db_connected
async def page(
    name: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    page: int = 1,
    page_size: int = 20,
    tenant_id: int | None = None,
    current_user: CurrentUser | None = None,
) -> PageRecord:
    if current_user is None:
        raise BusiException("当前用户不能为空", status_code=401)
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0:
        raise BusiException("page_size 必须大于 0")
    tenant_id = await _resolve_tenant_scope(current_user, tenant_id)

    filters: dict[str, Any] = {
        "name": common_utils.normalize_optional_filter(name),
        "owner_id": owner_id,
        "visibility": visibility,
        "tenant_id": tenant_id,
    }
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await knowledge_base_db.page(DB.get(), page=page, page_size=page_size, **filters)


__all__ = (
    "validate", "add", "modify", "remove", "get", "prompt_history", "organization_grants",
    "available_organizations", "grant_organization", "batch_grant_organizations",
    "revoke_organization", "user_grants", "available_users", "grant_user",
    "batch_grant_users", "revoke_user", "list", "page",
)
