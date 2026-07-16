from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from app.config import CONF
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


async def upload(
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

    # 当前阶段先落本地文件，后续接入 MinIO 时可替换为对象存储写入。
    storage_dir = Path(CONF.default.local_storage_dir or "./storage")
    # 示例：kb_id=1 时，target_dir 为 ./storage/documents/1。
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

    content_hash = hasher.hexdigest()
    object_path = target_dir.joinpath(f"{content_hash}_{filename}")
    temp_path.replace(object_path)
    # 转成 POSIX 风格字符串保存到数据库，例如 storage/documents/1/xxx.pdf。
    object_path = object_path.as_posix()
    return object_path, size, content_hash


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
    kb_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if not kb_id:
        raise BusiException("kb_id 不能为空")

    return await document_db.list(
        DB.get(),
        kb_id=kb_id,
        status=status,
    )


__all__ = (
    "validate",
    "upload",
    "add",
    "modify",
    "remove",
    "get",
    "list",
)
