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
from app.db import knowledge_base_index_version as index_version_db
from app.db import knowledge_base_qa_config as qa_config_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.rag import embeddings, loaders, splitters

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
async def create_task(document_id: int) -> Any:
    rd = None

    if not document_id:
        raise BusiException("document_id 不能为空")

    db = DB.get()
    async with db.transaction():
        document = await document_db.get(db, id=document_id)
        if document is None:
            raise BusiException("文档不存在", status_code=404)

        knowledge_base = await knowledge_base_db.get(db, id=document["kb_id"])
        active_index = None
        if knowledge_base and knowledge_base.get("active_index_version_id"):
            active_index = await index_version_db.get(
                db,
                id=knowledge_base["active_index_version_id"],
            )

        for task_status in RUNNING_TASK_STATUSES:
            task_filters = {
                "document_id": document_id,
                "status": task_status,
            }
            if active_index is not None:
                task_filters["index_version_id"] = active_index["id"]
            tasks = await indexing_task_db.list(
                db,
                **task_filters,
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
            config_version_id=active_index.get("config_version_id") if active_index else None,
            index_version_id=active_index["id"] if active_index else None,
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
        if await _task_uses_active_index(db, task):
            await document_db.update_(
                db,
                {
                    "status": DOCUMENT_STATUS_PROCESSING,
                    "updated_at": common_utils.utc_now(),
                },
                id=task["document_id"],
            )

    try:
        return await exc_task_body(task_id)
    except BusiException as exc:
        await mark_failed(task_id, exc.message)
        raise
    except Exception as exc:
        await mark_failed(task_id, str(exc))
        raise BusiException("索引任务执行失败") from exc


@check_db_connected
async def exc_task_body(task_id: int) -> Any:
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

        config_version = None
        if task.get("config_version_id"):
            config_version = await qa_config_db.get_version(
                db,
                id=task["config_version_id"],
                kb_id=document["kb_id"],
            )
        document_config = (config_version or {}).get("config_json", {}).get("document", {})
        chunk_size = int(document_config.get("chunk_size") or knowledge_base["chunk_size"])
        chunk_overlap_value = document_config.get("chunk_overlap")
        chunk_overlap = int(
            knowledge_base["chunk_overlap"]
            if chunk_overlap_value is None
            else chunk_overlap_value
        )
        chunks = splitters.split_documents(
            parsed_documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        if not chunks:
            raise BusiException("文档切片结果为空")

        chunks = await embeddings.embed_chunks(
            chunks,
            model=knowledge_base["embedding_model"],
        )
        await save_chunks(
            db,
            document,
            knowledge_base,
            chunks,
            index_version_id=task.get("index_version_id"),
        )
        rd = await mark_ready(db, task, document)
    return rd


async def save_chunks(
    db,
    document: dict[str, Any],
    knowledge_base: dict[str, Any],
    chunks: list[dict[str, Any]],
    index_version_id: int | None = None,
) -> None:
    delete_filters = {"document_id": document["id"]}
    if index_version_id is not None:
        delete_filters["index_version_id"] = index_version_id
    await document_chunk_db.delete_(db, **delete_filters)
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
                "embedding_model": (
                    chunk.get("embedding_model") or knowledge_base["embedding_model"]
                ),
                "embedding": chunk.get("embedding"),
                "index_version_id": index_version_id,
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
    await _activate_index_if_complete(db, task)
    if await _task_uses_active_index(db, task):
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


async def _task_uses_active_index(db, task: dict[str, Any]) -> bool:
    """判断任务是否属于当前生效索引，避免重建期间污染旧索引状态。"""
    index_version_id = task.get("index_version_id")
    if index_version_id is None:
        return True
    knowledge_base = await knowledge_base_db.get(db, id=task["kb_id"])
    return bool(
        knowledge_base
        and knowledge_base.get("active_index_version_id") == index_version_id
    )


async def _activate_index_if_complete(db, task: dict[str, Any]) -> None:
    index_version_id = task.get("index_version_id")
    if not index_version_id:
        return
    tasks = await indexing_task_db.list(db, index_version_id=index_version_id)
    if not tasks or any(item["status"] != TASK_STATUS_SUCCEEDED for item in tasks):
        return
    index_version = await index_version_db.get(db, id=index_version_id)
    if index_version is None or index_version.get("status") == "active":
        return
    knowledge_base = await knowledge_base_db.get(db, id=task["kb_id"])
    if knowledge_base is None:
        raise BusiException("知识库不存在", status_code=404)
    old_index_id = knowledge_base.get("active_index_version_id")
    if old_index_id and old_index_id != index_version_id:
        await index_version_db.update_(
            db,
            {"status": "retired", "retired_at": common_utils.utc_now()},
            id=old_index_id,
        )
    await index_version_db.update_(
        db,
        {
            "status": "active",
            "activated_at": common_utils.utc_now(),
        },
        id=index_version_id,
    )
    await knowledge_base_db.update_(
        db,
        {
            "active_index_version_id": index_version_id,
            "updated_at": common_utils.utc_now(),
        },
        id=task["kb_id"],
    )


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
        if await _task_uses_active_index(db, task):
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
    "create_task",
    "run_task",
    "exc_task_body",
    "save_chunks",
    "mark_ready",
    "mark_failed",
)
