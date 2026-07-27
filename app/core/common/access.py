from __future__ import annotations

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import guest as guest_service
from app.db import document as document_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db import platform_role as platform_role_db
from app.db.base import DB
from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN


async def _is_platform_super_admin(current_user: CurrentUser) -> bool:
    try:
        user_id = int(current_user.user_id)
    except (TypeError, ValueError):
        raise BusiException("当前用户无效", status_code=401) from None
    roles = await platform_role_db.get_user(DB.get(), user_id)
    return any(
        role.get("code") == PLATFORM_ROLE_SUPER_ADMIN and role.get("status") == "active"
        for role in roles
    )


async def require_knowledge_base_access(current_user: CurrentUser, knowledge_base_id: int) -> dict:
    if await _is_platform_super_admin(current_user):
        knowledge_base = await knowledge_base_db.get(DB.get(), id=knowledge_base_id)
        if knowledge_base is None or knowledge_base.get("status") == "deleted":
            raise BusiException("知识库不存在", status_code=404)
        return knowledge_base
    if current_user.tenant_id is None:
        raise BusiException("当前用户未选择租户", status_code=403)
    user_id, tenant_id, organization_ids = await guest_service._access_context(current_user)
    knowledge_base = await knowledge_base_db.guest_get(
        DB.get(), tenant_id, user_id, organization_ids, knowledge_base_id
    )
    if knowledge_base is None:
        raise BusiException("当前用户无权访问该知识库", status_code=403)
    return knowledge_base


async def require_document_access(current_user: CurrentUser, document_id: int) -> dict:
    document = await document_db.get(DB.get(), id=document_id)
    if document is None or document.get("status") == "deleted":
        raise BusiException("文档不存在", status_code=404)
    await require_knowledge_base_access(current_user, int(document["kb_id"]))
    return document


async def require_task_access(current_user: CurrentUser, document_id: int, task_id: int) -> dict:
    document = await require_document_access(current_user, document_id)
    task = await indexing_task_db.get(DB.get(), id=task_id, document_id=document_id)
    if task is None:
        raise BusiException("索引任务不存在", status_code=404)
    return task


__all__ = (
    "require_document_access",
    "require_knowledge_base_access",
    "require_task_access",
)
