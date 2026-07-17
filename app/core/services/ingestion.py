from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core import storage as object_storage
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import document as document_db
from app.db import document_chunk as document_chunk_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import loaders, splitters

DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_FAILED = "failed"
TASK_TYPE_INDEX = "index"
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
RUNNING_TASK_STATUSES = {TASK_STATUS_PENDING, TASK_STATUS_RUNNING}


@check_db_connected
async def create_index_task(document_id: int) -> Any:
    rd = None

    if not document_id:
        raise BusiException("document_id 不能为空")

    db = DB.get()
    async with db.transaction():
        document = await document_db.get(db, id=document_id)
        if document is None:
            raise BusiException("文档不存在", status_code=404)

        for task_status in RUNNING_TASK_STATUSES:
            tasks = await indexing_task_db.list(
                db,
                document_id=document_id,
                status=task_status,
            )
            if tasks:
                rd = tasks[0]
                return rd

        task_id = await indexing_task_db.insert_(
            db,
            document_id=document_id,
            kb_id=document["kb_id"],
            task_type=TASK_TYPE_INDEX,
            status=TASK_STATUS_PENDING,
        )
        rd = await indexing_task_db.get(db, id=task_id)
    if rd is None:
        raise BusiException("索引任务创建失败")
    return rd


@check_db_connected
async def run_task(task_id: int) -> Any:
    if not task_id:
        raise BusiException("task_id 不能为空")

    db = DB.get()
    async with db.transaction():
        task = await indexing_task_db.get(db, id=task_id)
        if task is None:
            raise BusiException("索引任务不存在", status_code=404)
        if task["status"] == TASK_STATUS_RUNNING:
            return task

        await indexing_task_db.update_(
            db,
            {
                "status": TASK_STATUS_RUNNING,
                "started_at": common_utils.utc_now(),
                "updated_at": common_utils.utc_now(),
                "attempts": int(task.get("attempts") or 0) + 1,
            },
            id=task_id,
        )
        await document_db.update_(
            db,
            {
                "status": DOCUMENT_STATUS_PROCESSING,
                "updated_at": common_utils.utc_now(),
            },
            id=task["document_id"],
        )

    try:
        return await _run_task_body(task_id)
    except BusiException as exc:
        await mark_failed(task_id, exc.message)
        raise
    except Exception as exc:
        await mark_failed(task_id, str(exc))
        raise BusiException("索引任务执行失败") from exc


@check_db_connected
async def _run_task_body(task_id: int) -> Any:
    rd = None

    db = DB.get()
    async with db.transaction():
        task = await indexing_task_db.get(db, id=task_id)
        if task is None:
            raise BusiException("索引任务不存在", status_code=404)

        document = await document_db.get(db, id=task["document_id"])
        if document is None:
            raise BusiException("文档不存在", status_code=404)

        knowledge_base = await knowledge_base_db.get(db, id=document["kb_id"])
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)

        # document.object_path 保存的是 MinIO object key，解析前先下载到本地临时文件。
        suffix = Path(document["object_path"]).suffix
        with TemporaryDirectory() as temp_dir:
            local_path = Path(temp_dir).joinpath(f"document_{document['id']}{suffix}")
            await object_storage.download_file(document["object_path"], local_path)
            local_document = dict(document)
            local_document["object_path"] = local_path.as_posix()
            parsed_documents = loaders.load_document(local_document)
        if not parsed_documents:
            raise BusiException("文档解析结果为空")

        chunks = splitters.split_documents(
            parsed_documents,
            chunk_size=knowledge_base["chunk_size"],
            chunk_overlap=knowledge_base["chunk_overlap"],
        )
        if not chunks:
            raise BusiException("文档切片结果为空")

        await save_chunks(db, document, knowledge_base, chunks)
        rd = await mark_ready(db, task, document)
    return rd


async def save_chunks(
    db,
    document: dict[str, Any],
    knowledge_base: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> None:
    await document_chunk_db.delete_(db, document_id=document["id"])
    rows = []
    for index, chunk in enumerate(chunks):
        content = chunk.get("content") or ""
        rows.append(
            {
                "kb_id": document["kb_id"],
                "document_id": document["id"],
                "parent_id": chunk.get("parent_id"),
                "chunk_index": chunk.get("chunk_index", index),
                "content": content,
                "content_hash": chunk.get("content_hash") or common_utils.hash_text(content),
                "source_name": document["source_name"],
                "page": chunk.get("page"),
                "section": chunk.get("section"),
                "start_index": chunk.get("start_index"),
                "token_count": chunk.get("token_count"),
                "metadata": chunk.get("metadata") or {},
                "embedding_model": knowledge_base["embedding_model"],
                "embedding": chunk.get("embedding"),
            }
        )
    await document_chunk_db.batch_insert(db, rows)


async def mark_ready(
    db,
    task: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any] | None:
    now = common_utils.utc_now()
    await indexing_task_db.update_(
        db,
        {
            "status": TASK_STATUS_SUCCEEDED,
            "finished_at": now,
            "updated_at": now,
        },
        id=task["id"],
    )
    await document_db.update_(
        db,
        {
            "status": DOCUMENT_STATUS_READY,
            "error_message": None,
            "updated_at": now,
        },
        id=document["id"],
    )
    return await indexing_task_db.get(db, id=task["id"])


@check_db_connected
async def mark_failed(task_id: int, error_message: str) -> Any:
    rd = None

    if not task_id:
        raise BusiException("task_id 不能为空")

    db = DB.get()
    async with db.transaction():
        task = await indexing_task_db.get(db, id=task_id)
        if task is None:
            raise BusiException("索引任务不存在", status_code=404)

        now = common_utils.utc_now()
        await indexing_task_db.update_(
            db,
            {
                "status": TASK_STATUS_FAILED,
                "error_message": error_message,
                "finished_at": now,
                "updated_at": now,
            },
            id=task_id,
        )
        await document_db.update_(
            db,
            {
                "status": DOCUMENT_STATUS_FAILED,
                "error_message": error_message,
                "updated_at": now,
            },
            id=task["document_id"],
        )
        rd = await indexing_task_db.get(db, id=task_id)
    return rd


__all__ = (
    "create_index_task",
    "run_task",
    "save_chunks",
    "mark_ready",
    "mark_failed",
)
