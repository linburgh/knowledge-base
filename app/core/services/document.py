from __future__ import annotations

from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import document as document_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.document import DocumentCreateDto, DocumentModifyDto

STATUS_PENDING = "pending"
STATUS_DELETED = "deleted"
TASK_TYPE_INDEX = "index"
TASK_STATUS_PENDING = "pending"


def validate(dto: DocumentCreateDto | DocumentModifyDto, is_create: bool = False) -> None:
    if dto is None:
        raise BusiException("文档参数不能为空")
    if is_create:
        if not dto.knowledge_base_id:
            raise BusiException("knowledge_base_id 不能为空")
        if not dto.source_type:
            raise BusiException("source_type 不能为空")
        if not dto.source_name:
            raise BusiException("source_name 不能为空")
        if not dto.content_type:
            raise BusiException("content_type 不能为空")
        if not dto.object_path:
            raise BusiException("object_path 不能为空")
        if not dto.content_hash:
            raise BusiException("content_hash 不能为空")
        if not dto.created_by:
            raise BusiException("created_by 不能为空")
    if dto.file_size is not None and dto.file_size < 0:
        raise BusiException("file_size 不能小于 0")


@check_db_connected
async def add(dto: DocumentCreateDto) -> Any:
    rd = None

    validate(dto, is_create=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("file_size", 0)
    values.setdefault("status", STATUS_PENDING)

    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=dto.knowledge_base_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)

        id = await document_db.insert_(db, **values)
        await indexing_task_db.insert_(
            db,
            document_id=id,
            knowledge_base_id=dto.knowledge_base_id,
            task_type=TASK_TYPE_INDEX,
            status=TASK_STATUS_PENDING,
        )
        rd = await document_db.get(db, id=id)
    if rd is None:
        raise BusiException("文档创建失败")
    return rd


@check_db_connected
async def modify(id: int, dto: DocumentModifyDto) -> Any:
    rd = None

    if not id:
        raise BusiException("document_id 不能为空")
    validate(dto)

    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")

    db = DB.get()
    async with db.transaction():
        old = await document_db.get(db, id=id)
        if old is None:
            raise BusiException("文档不存在", status_code=404)

        values["updated_at"] = common_utils.utc_now()
        await document_db.update_(db, values, id=id)
        rd = await document_db.get(db, id=id)
    return rd


@check_db_connected
async def remove(id: int) -> Any:
    rd = None

    if not id:
        raise BusiException("document_id 不能为空")

    db = DB.get()
    async with db.transaction():
        old = await document_db.get(db, id=id)
        if old is None:
            raise BusiException("文档不存在", status_code=404)

        await document_db.update_(
            db,
            {
                "status": STATUS_DELETED,
                "updated_at": common_utils.utc_now(),
            },
            id=id,
        )
        rd = await document_db.get(db, id=id)
    return rd


@check_db_connected
async def get(id: int) -> dict[str, Any]:
    if not id:
        raise BusiException("document_id 不能为空")

    row = await document_db.get(DB.get(), id=id)
    if row is None:
        raise BusiException("文档不存在", status_code=404)
    return row


@check_db_connected
async def list(
    knowledge_base_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")

    return await document_db.list(
        DB.get(),
        knowledge_base_id=knowledge_base_id,
        status=status,
    )


__all__ = (
    "validate",
    "add",
    "modify",
    "remove",
    "get",
    "list",
)
