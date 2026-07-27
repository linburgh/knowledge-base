from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from app.config import CONF
from app.core import storage as object_storage
from app.core.common import access as access_service
from app.core.common import utils as common_utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.core.services import ingestion as ingestion_service
from app.db import document as document_db
from app.db import document_chunk as document_chunk_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.document import DocumentCreateDto, DocumentModifyDto

STATUS_PENDING = "pending"
STATUS_DELETED = "deleted"
TASK_TYPE_INDEX = "index"
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
UPLOAD_CHUNK_SIZE = 1024 * 1024


class UploadFileLike(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes:
        ...


def validate(dto: DocumentCreateDto | DocumentModifyDto, is_create: bool = False) -> None:
    if dto is None:
        raise BusiException("文档参数不能为空")
    if is_create:
        if not dto.kb_id:
            raise BusiException("kb_id 不能为空")
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


async def upload_file(
    file: UploadFileLike,
    kb_id: int,
) -> tuple[str, int, str]:
    # 只保留文件名，避免用户传入带目录的路径影响保存位置。
    filename = Path(file.filename or "").name
    if not filename:
        raise BusiException("上传文件名不能为空")

    suffix = Path(filename).suffix.lower()

    allowed_extensions = set(CONF.default.allowed_file_extensions or [])
    if suffix not in allowed_extensions:
        raise BusiException("不支持的文件类型")

    storage_dir = Path(CONF.storage.local_dir or "./storage")
    # MinIO 是正式存储；本地目录只用于暂存上传流。
    # 例如 kb_id=1 时，target_dir 为 ./storage/documents/1。
    target_dir = storage_dir.joinpath("documents", str(kb_id))
    target_dir.mkdir(parents=True, exist_ok=True)

    max_size = int(CONF.default.max_upload_size_mb or 100) * 1024 * 1024
    hasher = sha256()
    size = 0
    # 最终文件名依赖内容 hash，上传完成前先写入临时文件。
    temp_path = target_dir.joinpath(f".upload_{common_utils.new_request_id()}.tmp")
    try:
        with temp_path.open("wb") as target_file:
            # 分块读取避免把完整文件一次性加载到内存，同时可以边读边校验大小和计算 hash。
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > max_size:
                    raise BusiException("上传文件超过大小限制")
                hasher.update(chunk)
                target_file.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise BusiException("上传文件不能为空")

    content_hash = hasher.hexdigest()
    # 数据库保存 MinIO object key，例如 documents/1/{sha256}_readme.md。
    object_name = f"documents/{kb_id}/{content_hash}_{filename}"
    try:
        content_type = getattr(file, "content_type", None) or "application/octet-stream"
        await object_storage.upload_file(
            object_name,
            temp_path,
            content_type=content_type,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    return object_name, size, content_hash


async def upload(
    file: UploadFileLike,
    kb_id: int,
    created_by: str,
    source_type: str = "upload",
    parser: str | None = None,
) -> Any:
    object_path, file_size, content_hash = await upload_file(file, kb_id)
    dto = DocumentCreateDto(
        kb_id=kb_id,
        source_type=source_type,
        source_name=Path(file.filename or object_path).name,
        source_uri=None,
        content_type=getattr(file, "content_type", None) or "application/octet-stream",
        object_path=object_path,
        file_size=file_size,
        content_hash=content_hash,
        parser=parser,
        created_by=created_by,
    )
    document = await add(dto)
    await ingestion_service.create_task(document["id"])
    return document


@check_db_connected
async def add(dto: DocumentCreateDto) -> Any:
    rd = None

    validate(dto, is_create=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("file_size", 0)
    values.setdefault("status", STATUS_PENDING)

    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=dto.kb_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)

        id = await document_db.insert_(db, **values)
        await indexing_task_db.insert_(
            db,
            document_id=id,
            kb_id=dto.kb_id,
            task_type=TASK_TYPE_INDEX,
            status=TASK_STATUS_PENDING,
        )
        rd = await document_db.get(db, id=id)
        await audit_service.record(
            db, action="create_document", target_type="document", target_id=id,
            summary={"after": rd},
        )
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
        await audit_service.record(
            db, action="update_document", target_type="document", target_id=id,
            summary={"changed_fields": list(values), "before": old, "after": rd},
        )
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
        await audit_service.record(
            db, action="delete_document", target_type="document", target_id=id,
            summary={"before": old, "after": rd},
        )
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
    kb_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if not kb_id:
        raise BusiException("kb_id 不能为空")

    filters: dict[str, Any] = {"kb_id": kb_id}
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await document_db.list(DB.get(), **filters)


@check_db_connected
async def list_chunks(document_id: int) -> list[dict[str, Any]]:
    if not document_id:
        raise BusiException("document_id 不能为空")
    db = DB.get()
    document = await document_db.get(db, id=document_id)
    if document is None:
        raise BusiException("文档不存在", status_code=404)
    return await document_chunk_db.list(db, document_id=document_id)


def _index_task_response(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if task is None:
        return None
    result = dict(task)
    result["progress"] = max(0, min(100, int(result.get("progress") or 0)))
    result["current_step"] = result.get("current_step") or {
        TASK_STATUS_PENDING: "等待处理",
        TASK_STATUS_RUNNING: "处理中",
        TASK_STATUS_SUCCEEDED: "完成",
        TASK_STATUS_FAILED: "失败",
    }.get(result.get("status"), "未知")
    started_at = result.get("started_at")
    finished_at = result.get("finished_at")
    if started_at and finished_at:
        result["duration_seconds"] = max(0, int((finished_at - started_at).total_seconds()))
    elif started_at:
        result["duration_seconds"] = max(
            0,
            int((common_utils.utc_now() - started_at).total_seconds()),
        )
    else:
        result["duration_seconds"] = 0
    return result


@check_db_connected
async def get_index_progress(
    document_id: int,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 50:
        raise BusiException("历史任务分页参数不合法")
    document = await access_service.require_document_access(current_user, document_id)
    db = DB.get()
    history = await indexing_task_db.page(
        db,
        page=page,
        page_size=page_size,
        document_id=document_id,
    )
    current_task = None
    for status in (TASK_STATUS_PENDING, TASK_STATUS_RUNNING):
        active_tasks = await indexing_task_db.list(
            db,
            document_id=document_id,
            status=status,
            limit=1,
        )
        if active_tasks:
            current_task = active_tasks[0]
            break
    if current_task is None and history["items"]:
        current_task = history["items"][0]
    history["items"] = [_index_task_response(item) for item in history["items"]]
    return {
        "document": document,
        "current_task": _index_task_response(current_task),
        "history": history,
    }


@check_db_connected
async def rebuild_index(document_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await access_service.require_document_access(current_user, document_id)
    return await ingestion_service.create_task(document_id)


__all__ = (
    "validate",
    "upload",
    "add",
    "modify",
    "remove",
    "get",
    "list",
    "list_chunks",
    "get_index_progress",
    "rebuild_index",
)
