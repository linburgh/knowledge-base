from __future__ import annotations

from typing import Any

from app.config import CONF
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord
from app.schemas.knowledge_base import KnowledgeBaseDto

STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"
DEFAULT_VISIBILITY = "private"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_RETRIEVAL_TOP_K = 5
MAX_DESCRIPTION_LENGTH = 500


def validate(dto: KnowledgeBaseDto) -> None:
    if dto is None:
        raise BusiException("知识库参数不能为空")
    
    if not dto.name:
        raise BusiException("name 不能为空")
    if not dto.owner_id:
        raise BusiException("owner_id 不能为空")
    if dto.description is not None and len(dto.description) > MAX_DESCRIPTION_LENGTH:
        raise BusiException("description 不能超过 500 个字符")
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
    values.setdefault("status", STATUS_ACTIVE)

    db = DB.get()
    async with db.transaction():
        knowledge_base_id = await knowledge_base_db.insert_(db, **values)
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
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

        values["updated_at"] = common_utils.utc_now()
        await knowledge_base_db.update_(db, values, id=knowledge_base_id)
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
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

        await knowledge_base_db.update_(
            db,
            {
                "status": STATUS_DELETED,
                "updated_at": common_utils.utc_now(),
            },
            id=knowledge_base_id,
        )
        rd = await knowledge_base_db.get(db, id=knowledge_base_id)
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
async def list(
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {"owner_id": owner_id, "visibility": visibility}
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await knowledge_base_db.list(DB.get(), **filters)


@check_db_connected
async def page(
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageRecord:
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0:
        raise BusiException("page_size 必须大于 0")

    filters: dict[str, Any] = {"owner_id": owner_id, "visibility": visibility}
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await knowledge_base_db.page(DB.get(), page=page, page_size=page_size, **filters)


__all__ = ("validate", "add", "modify", "remove", "get", "list", "page")
