from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile, status

from app.config import CONF
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import document as document_service
from app.core.services import ingestion as ingestion_service
from app.schemas.document import (
    DocumentCreateDto,
    DocumentCreateRequest,
    DocumentModifyDto,
    DocumentModifyRequest,
)

router = APIRouter()


def _validate_upload_file(filename: str, size: int) -> None:
    suffix = Path(filename).suffix.lower()
    allowed_extensions = set(CONF.default.allowed_file_extensions or [])
    if suffix not in allowed_extensions:
        raise BusiException("不支持的文件类型")

    max_size = int(CONF.default.max_upload_size_mb or 20) * 1024 * 1024
    if size > max_size:
        raise BusiException("上传文件超过大小限制")


async def _save_upload_file(
    file: UploadFile,
    knowledge_base_id: int,
) -> tuple[str, int, str]:
    filename = Path(file.filename or "").name
    if not filename:
        raise BusiException("上传文件名不能为空")

    content = await file.read()
    size = len(content)
    _validate_upload_file(filename, size)

    content_hash = common_utils.hash_bytes(content)
    storage_dir = Path(CONF.default.local_storage_dir or "./storage")
    target_dir = storage_dir.joinpath("documents", str(knowledge_base_id))
    target_dir.mkdir(parents=True, exist_ok=True)

    object_path = target_dir.joinpath(f"{content_hash}_{filename}")
    object_path.write_bytes(content)
    return object_path.as_posix(), size, content_hash


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(
    knowledge_base_id: Annotated[int, Form(...)],
    created_by: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    source_type: Annotated[str, Form()] = "upload",
    parser: Annotated[str | None, Form()] = None,
) -> Any:
    try:
        object_path, file_size, content_hash = await _save_upload_file(file, knowledge_base_id)
        dto = DocumentCreateDto(
            knowledge_base_id=knowledge_base_id,
            source_type=source_type,
            source_name=Path(file.filename or object_path).name,
            source_uri=None,
            content_type=file.content_type or "application/octet-stream",
            object_path=object_path,
            file_size=file_size,
            content_hash=content_hash,
            parser=parser,
            created_by=created_by,
        )
        return await document_service.add(dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: DocumentCreateRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, DocumentCreateDto)
        return await document_service.add(dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: DocumentModifyRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, DocumentModifyDto)
        return await document_service.modify(id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await document_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await document_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    knowledge_base_id: int,
    status: str | None = None,
) -> Any:
    try:
        return await document_service.list(knowledge_base_id, status=status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{id}/index")
async def index(id: int) -> Any:
    try:
        task = await ingestion_service.create_index_task(id)
        return await ingestion_service.run_task(task["id"])
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
