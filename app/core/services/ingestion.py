from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.config import CONF
from app.core import storage as object_storage
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.monitoring import emit_gather_event, monitor_gather
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
DOCUMENT_STATUS_INTERRUPTED = "interrupted"
DOCUMENT_STATUS_CANCELED = "canceled"
TASK_TYPE_INDEX = "index"
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_INTERRUPTED = "interrupted"
TASK_STATUS_CANCELED = "canceled"
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
            progress=0,
            current_step="等待处理",
            config_version_id=active_index.get("config_version_id") if active_index else None,
            index_version_id=active_index["id"] if active_index else None,
        )
        await document_db.update_(
            db,
            {
                "status": DOCUMENT_STATUS_PROCESSING,
                "error_message": None,
                "updated_at": common_utils.utc_now(),
            },
            id=document_id,
        )
        rd = await indexing_task_db.get(db, id=task_id)
    if rd is None:
        raise BusiException("索引任务创建失败")
    return rd


async def _execute_claimed_task(task_id: int) -> Any:
    try:
        return await asyncio.wait_for(
            exc_task_body(task_id),
            timeout=max(1, int(CONF.default.indexing_task_timeout_seconds)),
        )
    except TimeoutError:
        message = "索引任务超过最大执行时间"
        await emit_gather_event(
            "document.indexing",
            "indexing_timeout",
            args=(task_id,),
            task_id=task_id,
            timeout_stage="indexing_execution",
        )
        await mark_failed(task_id, message)
        raise BusiException(message) from None
    except BusiException as exc:
        latest = await indexing_task_db.get(DB.get(), id=task_id)
        if latest and latest["status"] not in {TASK_STATUS_INTERRUPTED, TASK_STATUS_CANCELED}:
            await mark_failed(task_id, exc.message)
        raise
    except Exception as exc:
        latest = await indexing_task_db.get(DB.get(), id=task_id)
        if latest and latest["status"] not in {TASK_STATUS_INTERRUPTED, TASK_STATUS_CANCELED}:
            await mark_failed(task_id, str(exc))
        raise BusiException("索引任务执行失败") from exc


@check_db_connected
@monitor_gather("document.indexing")
async def run_claimed_task(task_id: int) -> Any:
    """Execute a task that was atomically claimed by the scheduler."""
    if not task_id:
        raise BusiException("task_id 不能为空")

    task = await indexing_task_db.get(DB.get(), id=task_id)
    if task is None:
        raise BusiException("索引任务不存在", status_code=404)
    if task["status"] != TASK_STATUS_RUNNING:
        raise BusiException("索引任务尚未领取", status_code=409)
    return await _execute_claimed_task(task_id)


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
        if task["status"] != TASK_STATUS_PENDING:
            raise BusiException("当前任务状态不可执行", status_code=409)

        await indexing_task_db.update_(
            db,
            {
                "status": TASK_STATUS_RUNNING,
                "progress": max(int(task.get("progress") or 0), 5),
                "current_step": "解析原始文件",
                "started_at": common_utils.utc_now(),
                "updated_at": common_utils.utc_now(),
                "attempts": int(task.get("attempts") or 0) + 1,
            },
            id=task_id,
        )
        if await _task_can_update_document_status(db, task):
            await document_db.update_(
                db,
                {
                    "status": DOCUMENT_STATUS_PROCESSING,
                    "updated_at": common_utils.utc_now(),
                },
                id=task["document_id"],
            )

    return await _execute_claimed_task(task_id)


@check_db_connected
async def exc_task_body(task_id: int) -> Any:
    db = DB.get()
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

    await _update_task_progress(task_id, 25, "切分文档内容")

    config_version = None
    if task.get("config_version_id"):
        config_version = await qa_config_db.get_version(
            db,
            id=task["config_version_id"],
            kb_id=document["kb_id"],
        )
    document_config = (config_version or {}).get("config_json", {}).get("document", {})
    embedding_model = document_config.get("embedding_model") or knowledge_base["embedding_model"]
    chunk_size = int(document_config.get("chunk_size") or knowledge_base["chunk_size"])
    chunk_overlap_value = document_config.get("chunk_overlap")
    chunk_overlap = int(
        knowledge_base["chunk_overlap"] if chunk_overlap_value is None else chunk_overlap_value
    )
    chunks = splitters.split_documents(
        parsed_documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    if not chunks:
        raise BusiException("文档切片结果为空")

    await _update_task_progress(task_id, 40, "生成 Embedding 向量")

    chunks = await embeddings.embed_chunks(
        chunks,
        model=embedding_model,
        batch_size=CONF.embedding.batch_size,
        concurrency=CONF.embedding.concurrency,
        retry_count=CONF.embedding.retry_count,
        progress_callback=lambda completed, total: _touch_task(task_id, completed, total),
    )
    await _update_task_progress(task_id, 90, "写入索引")

    # 仅把分片替换和任务完成放在短事务中，避免网络调用期间长期占用数据库连接。
    async with db.transaction():
        current_task = await indexing_task_db.get(db, id=task_id)
        if current_task is None or current_task["status"] != TASK_STATUS_RUNNING:
            raise BusiException("索引任务已中断")
        await save_chunks(
            db,
            document,
            knowledge_base,
            chunks,
            embedding_model=embedding_model,
            index_version_id=task.get("index_version_id"),
        )
        completed_task = await mark_ready(db, task, document)
        if completed_task is None:
            return None
        result = dict(completed_task)
        result["document_id"] = document["id"]
        result["chunk_count"] = len(chunks)
        return result


@check_db_connected
async def _touch_task(task_id: int, completed: int | None = None, total: int | None = None) -> None:
    db = DB.get()
    values: dict[str, Any] = {
        "updated_at": common_utils.utc_now(),
        "current_step": "生成 Embedding 向量",
    }
    if completed is not None and total and total > 0:
        values["progress"] = min(89, 40 + int((completed / total) * 49))
    async with db.transaction():
        await indexing_task_db.update_(
            db,
            values,
            id=task_id,
            status=TASK_STATUS_RUNNING,
        )


@check_db_connected
async def _update_task_progress(task_id: int, progress: int, current_step: str) -> None:
    db = DB.get()
    async with db.transaction():
        await indexing_task_db.update_(
            db,
            {
                "progress": max(0, min(100, progress)),
                "current_step": current_step,
                "updated_at": common_utils.utc_now(),
            },
            id=task_id,
            status=TASK_STATUS_RUNNING,
        )


@check_db_connected
async def recover_stale_tasks() -> int:
    """Recover tasks left running by a process restart or worker failure."""
    db = DB.get()
    now = common_utils.utc_now()
    stale_before = now - timedelta(seconds=max(1, int(CONF.default.indexing_stale_after_seconds)))
    tasks = await indexing_task_db.list(db, status=TASK_STATUS_RUNNING)
    recovered = 0
    for task in tasks:
        updated_at = task.get("updated_at") or task.get("started_at")
        if updated_at is None or updated_at > stale_before:
            continue
        attempts = int(task.get("attempts") or 0)
        max_attempts = int(task.get("max_attempts") or 3)
        if attempts >= max_attempts:
            await mark_failed(task["id"], "索引任务失联且已超过最大重试次数")
        else:
            async with db.transaction():
                await indexing_task_db.update_(
                    db,
                    {
                        "status": TASK_STATUS_PENDING,
                        "progress": 0,
                        "current_step": "等待恢复",
                        "error_message": "索引任务失联，等待自动恢复",
                        "updated_at": common_utils.utc_now(),
                    },
                    id=task["id"],
                    status=TASK_STATUS_RUNNING,
                )
        recovered += 1
    return recovered


async def save_chunks(
    db,
    document: dict[str, Any],
    knowledge_base: dict[str, Any],
    chunks: list[dict[str, Any]],
    embedding_model: str | None = None,
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
                    chunk.get("embedding_model")
                    or embedding_model
                    or knowledge_base["embedding_model"]
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
            "progress": 100,
            "current_step": "完成",
            "finished_at": now,
            "updated_at": now,
        },
        id=task["id"],
        status=TASK_STATUS_RUNNING,
    )
    completed_task = await indexing_task_db.get(db, id=task["id"])
    if not completed_task or completed_task["status"] != TASK_STATUS_SUCCEEDED:
        return completed_task
    await _activate_index_if_complete(db, task)
    if await _task_can_update_document_status(db, task):
        await document_db.update_(
            db,
            {
                "status": DOCUMENT_STATUS_READY,
                "error_message": None,
                "updated_at": now,
            },
            id=document["id"],
        )
    return completed_task


async def _task_can_update_document_status(db, task: dict[str, Any]) -> bool:
    """只允许当前或更新中的索引任务更新文档状态。"""
    index_version_id = task.get("index_version_id")
    if index_version_id is None:
        return True
    knowledge_base = await knowledge_base_db.get(db, id=task["kb_id"])
    if knowledge_base is None:
        return False
    active_index_id = knowledge_base.get("active_index_version_id")
    return active_index_id is None or index_version_id >= active_index_id


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
            **await _active_index_config_values(db, task),
            "updated_at": common_utils.utc_now(),
        },
        id=task["kb_id"],
    )


async def _active_index_config_values(db, task: dict[str, Any]) -> dict[str, Any]:
    config_version_id = task.get("config_version_id")
    if not config_version_id:
        return {}
    config_version = await qa_config_db.get_version(
        db,
        id=config_version_id,
        kb_id=task["kb_id"],
    )
    embedding_model = (
        ((config_version or {}).get("config_json") or {}).get("document", {}).get("embedding_model")
    )
    return {"embedding_model": embedding_model} if embedding_model else {}


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
        if await _task_can_update_document_status(db, task):
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


@check_db_connected
async def interrupt_task(
    task_id: int,
    expected_version: int,
    error_message: str = "用户手动中断索引任务",
) -> Any:
    if not task_id:
        raise BusiException("task_id 不能为空")
    db = DB.get()
    async with db.transaction():
        task = await indexing_task_db.get(db, id=task_id)
        if task is None:
            raise BusiException("索引任务不存在", status_code=404)
        if task["status"] not in RUNNING_TASK_STATUSES:
            raise BusiException(
                f"当前任务状态不可中断：task_id={task_id}，当前状态={task['status']}，"
                f"进度={task.get('progress') or 0}%",
                status_code=409,
            )
        if int(task.get("version") or 0) != expected_version:
            raise BusiException(
                f"索引任务已发生变化：task_id={task_id}，"
                f"当前版本={task.get('version') or 0}，请求版本={expected_version}",
                status_code=409,
            )
        now = common_utils.utc_now()
        await indexing_task_db.update_(
            db,
            {
                "status": TASK_STATUS_CANCELED,
                "error_message": error_message,
                "finished_at": now,
                "updated_at": now,
            },
            id=task_id,
            status=task["status"],
            version=expected_version,
        )
        await document_db.update_(
            db,
            {"status": DOCUMENT_STATUS_CANCELED, "error_message": error_message, "updated_at": now},
            id=task["document_id"],
        )
        return await indexing_task_db.get(db, id=task_id)


__all__ = (
    "create_task",
    "run_task",
    "run_claimed_task",
    "exc_task_body",
    "save_chunks",
    "mark_ready",
    "mark_failed",
    "interrupt_task",
    "recover_stale_tasks",
)
