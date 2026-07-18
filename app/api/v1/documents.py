from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile, status

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


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(
    kb_id: Annotated[int, Form(...)],
    created_by: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    source_type: Annotated[str, Form()] = "upload",
    parser: Annotated[str | None, Form()] = None,
) -> Any:
    try:
        return await document_service.upload(
            file,
            kb_id,
            created_by,
            source_type=source_type,
            parser=parser,
        )
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


@router.get("/{id}/chunks")
async def chunks(id: int) -> Any:
    try:
        return await document_service.list_chunks(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    kb_id: int,
    status: str | None = None,
) -> Any:
    try:
        return await document_service.list(kb_id, status=status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{id}/index")
async def index(id: int) -> Any:
    try:
        task = await ingestion_service.create_task(id)
        return await ingestion_service.run_task(task["id"])
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
