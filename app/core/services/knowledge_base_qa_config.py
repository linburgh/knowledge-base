from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any

import sqlalchemy as sa

from app.config import CONF
from app.core.common import utils as common_utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import permission as permission_service
from app.core.services import retrieval as retrieval_service
from app.db import document as document_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db import knowledge_base_index_version as index_version_db
from app.db import knowledge_base_qa_config as qa_config_db
from app.db import platform_role as platform_role_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.db.models import Document
from app.rag.rerank import rerank

STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"
CONFIG_DRAFT = "draft"
CONFIG_PUBLISHED = "published"
CONFIG_ARCHIVED = "archived"
ACTION_UPDATE_CONFIG = "knowledge_base:update_config"

DOCUMENT_CONFIG_KEYS = {
    "chunk_size",
    "chunk_overlap",
    "title_preserved",
    "whitespace_cleaning",
    "table_strategy",
    "duplicate_strategy",
}
TOP_LEVEL_KEYS = {"document", "retrieval", "rerank", "answer", "agent"}
RETRIEVAL_MODES = {"vector", "keyword", "hybrid"}
EMPTY_RESULT_STRATEGIES = {"资料不足提示", "进入降级回答", "扩大召回"}
RERANK_FAIL_STRATEGIES = {"使用向量结果", "终止本次问答"}


def _option(group: str, name: str, default: Any) -> Any:
    try:
        return getattr(getattr(CONF, group), name)
    except AttributeError:
        return default


def default_config(system_prompt: str = "") -> dict[str, Any]:
    retrieval_top_k = int(_option("rag", "retrieval_top_k", 5))
    return {
        "document": {
            "chunk_size": int(_option("rag", "chunk_size", 600)),
            "chunk_overlap": int(_option("rag", "chunk_overlap", 100)),
            "title_preserved": True,
            "whitespace_cleaning": True,
            "table_strategy": "保留文本",
            "duplicate_strategy": "标记重复",
        },
        "retrieval": {
            "top_k": retrieval_top_k,
            "similarity_threshold": None,
            "mode": "vector",
            "hybrid_enabled": False,
            "keyword_weight": 30,
            "query_rewrite": False,
            "empty_result_strategy": "资料不足提示",
        },
        "rerank": {
            "enabled": bool(_option("rag", "rerank_enabled", False)),
            "model": str(_option("rag", "rerank_model", "")),
            "candidate_count": retrieval_top_k * int(
                _option("rag", "rerank_candidate_multiplier", 3)
            ),
            "final_return_count": retrieval_top_k,
            "timeout_seconds": int(_option("rag", "rerank_timeout_seconds", 30)),
            "fail_strategy": (
                "使用向量结果"
                if bool(_option("rag", "rerank_fail_open", True))
                else "终止本次问答"
            ),
        },
        "answer": {
            "style": "专业自然",
            "max_length": 300,
            "must_cite": True,
            "max_citations": 3,
            "insufficient_data_strategy": "明确说明资料不足",
            "high_risk_strategy": "谨慎回答",
            "fallback_enabled": True,
            "prompt": system_prompt or "只能依据知识库资料回答，资料不足时明确说明。",
        },
        "agent": {
            "max_steps": int(_option("agent", "max_steps", 4)),
            "max_tool_calls": int(_option("agent", "max_tool_calls", 6)),
            "total_timeout_seconds": float(_option("agent", "total_timeout_seconds", 60)),
            "tool_timeout_seconds": float(_option("agent", "tool_timeout_seconds", 10)),
            "max_retries": int(_option("agent", "max_retries", 1)),
            "recursion_limit": int(_option("agent", "max_steps", 4)),
            "fallback_timeout_seconds": 15,
        },
    }


def _merge_config(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for group, values in incoming.items():
        if isinstance(values, dict) and isinstance(result.get(group), dict):
            result[group].update(values)
        else:
            result[group] = values
    return result


def _positive_int(config: dict[str, Any], group: str, field: str) -> int:
    value = config[group].get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BusiException(f"{group}.{field} 必须是大于 0 的整数")
    return value


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise BusiException("config 必须是对象")
    unknown_groups = set(config) - TOP_LEVEL_KEYS
    if unknown_groups:
        raise BusiException(f"不支持的配置分组：{', '.join(sorted(unknown_groups))}")

    chunk_size = _positive_int(config, "document", "chunk_size")
    chunk_overlap = config["document"].get("chunk_overlap")
    if not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool) or chunk_overlap < 0:
        raise BusiException("document.chunk_overlap 必须是大于等于 0 的整数")
    if chunk_overlap >= chunk_size:
        raise BusiException("document.chunk_overlap 必须小于 document.chunk_size")

    top_k = _positive_int(config, "retrieval", "top_k")
    if top_k > 20:
        raise BusiException("retrieval.top_k 不能超过 20")
    mode = config["retrieval"].get("mode")
    if mode not in RETRIEVAL_MODES:
        raise BusiException("retrieval.mode 不合法")
    keyword_weight = config["retrieval"].get("keyword_weight")
    if not isinstance(keyword_weight, int) or not 0 <= keyword_weight <= 100:
        raise BusiException("retrieval.keyword_weight 必须在 0 到 100 之间")
    if config["retrieval"].get("hybrid_enabled") and mode != "hybrid":
        raise BusiException("开启混合检索时 retrieval.mode 必须为 hybrid")
    if config["retrieval"].get("empty_result_strategy") not in EMPTY_RESULT_STRATEGIES:
        raise BusiException("retrieval.empty_result_strategy 不合法")

    candidate_count = _positive_int(config, "rerank", "candidate_count")
    final_count = _positive_int(config, "rerank", "final_return_count")
    if final_count > candidate_count:
        raise BusiException("rerank.final_return_count 不能大于 candidate_count")
    if config["rerank"].get("fail_strategy") not in RERANK_FAIL_STRATEGIES:
        raise BusiException("rerank.fail_strategy 不合法")

    max_length = _positive_int(config, "answer", "max_length")
    if max_length > 10000:
        raise BusiException("answer.max_length 不能超过 10000")
    max_citations = _positive_int(config, "answer", "max_citations")
    if max_citations > 20:
        raise BusiException("answer.max_citations 不能超过 20")
    prompt = config["answer"].get("prompt")
    if not isinstance(prompt, str) or len(prompt) > 10000:
        raise BusiException("answer.prompt 不能为空且不能超过 10000 个字符")

    for field in ("max_steps", "max_tool_calls", "max_retries", "recursion_limit"):
        value = _positive_int(config, "agent", field)
        if value > 100:
            raise BusiException(f"agent.{field} 不能超过 100")
    for field in ("total_timeout_seconds", "tool_timeout_seconds", "fallback_timeout_seconds"):
        value = config["agent"].get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise BusiException(f"agent.{field} 必须是大于 0 的数字")


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for group in TOP_LEVEL_KEYS:
        before_group = before.get(group, {})
        after_group = after.get(group, {})
        group_changed = {
            key: {"before": before_group.get(key), "after": value}
            for key, value in after_group.items()
            if before_group.get(key) != value
        }
        if group_changed:
            changed[group] = group_changed
    return changed


async def get_effective_config(
    db,
    kb_id: int,
    system_prompt: str = "",
    version_id: int | None = None,
) -> dict[str, Any]:
    version = (
        await qa_config_db.get_version(db, id=version_id, kb_id=kb_id)
        if version_id is not None
        else await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_PUBLISHED)
    )
    if version and version.get("config_json"):
        return version["config_json"]
    return default_config(system_prompt)


async def _get_kb(db, kb_id: int, current_user: CurrentUser) -> dict[str, Any]:
    if kb_id <= 0:
        raise BusiException("kb_id 必须大于 0")
    knowledge_base = await knowledge_base_db.get(db, id=kb_id)
    if knowledge_base is None or knowledge_base.get("status") == STATUS_DELETED:
        raise BusiException("知识库不存在", status_code=404)
    platform_roles = await platform_role_db.get_user(db, int(current_user.user_id))
    is_platform_super_admin = any(
        role.get("code") == "p_super_admin" and role.get("status") == STATUS_ACTIVE
        for role in platform_roles
    )
    if (
        not is_platform_super_admin
        and current_user.tenant_id is not None
        and knowledge_base.get("tenant_id") != current_user.tenant_id
    ):
        raise BusiException("无权访问当前知识库", status_code=403)
    return knowledge_base


async def _require_edit_permission(current_user: CurrentUser) -> None:
    await permission_service.require_action(current_user, ACTION_UPDATE_CONFIG)


async def _document_count(db, kb_id: int) -> int:
    query = sa.select(sa.func.count()).select_from(Document).where(
        Document.c.kb_id == kb_id,
        Document.c.status != STATUS_DELETED,
    )
    return int(await db.fetch_val(query))


@check_db_connected
async def get_config(kb_id: int, current_user: CurrentUser) -> dict[str, Any]:
    db = DB.get()
    knowledge_base = await _get_kb(db, kb_id, current_user)
    published = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_PUBLISHED)
    draft = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_DRAFT)
    effective = (draft or published or {}).get("config_json")
    if not effective:
        effective = default_config(knowledge_base.get("system_prompt") or "")
    return {
        "kb_id": kb_id,
        "published": published,
        "draft": draft,
        "effective": effective,
        "has_draft": draft is not None,
    }


@check_db_connected
async def save_draft(
    kb_id: int,
    config: dict[str, Any],
    current_user: CurrentUser,
    base_version: int | None = None,
) -> dict[str, Any]:
    await _require_edit_permission(current_user)
    db = DB.get()
    knowledge_base = await _get_kb(db, kb_id, current_user)
    async with db.transaction():
        published = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_PUBLISHED)
        draft = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_DRAFT)
        current_version = draft or published
        if (
            base_version is not None
            and current_version
            and current_version["version_no"] != base_version
        ):
            raise BusiException("配置版本已变化，请重新加载后再保存", status_code=409)
        base_config = (current_version or {}).get("config_json") or default_config(
            knowledge_base.get("system_prompt") or ""
        )
        merged = _merge_config(base_config, config)
        validate_config(merged)
        published_config = (published or {}).get("config_json") or default_config(
            knowledge_base.get("system_prompt") or ""
        )
        changed = _changed_fields(published_config, merged)
        reindex = bool(set(changed.get("document", {})) & DOCUMENT_CONFIG_KEYS)
        affected_count = await _document_count(db, kb_id) if reindex else 0
        summary = {
            "changed_fields": changed,
            "requires_reindex": reindex,
            "affected_document_count": affected_count,
        }
        if draft:
            version_id = await qa_config_db.update_version(
                db,
                {
                    "config_json": merged,
                    "change_summary_json": summary,
                    "requires_reindex": reindex,
                    "affected_document_count": affected_count,
                    "updated_at": common_utils.utc_now(),
                },
                id=draft["id"],
            )
        else:
            version_no = await qa_config_db.next_version_no(db, kb_id)
            version_id = await qa_config_db.insert_version(
                db,
                kb_id=kb_id,
                version_no=version_no,
                status=CONFIG_DRAFT,
                config_json=merged,
                change_summary_json=summary,
                requires_reindex=reindex,
                affected_document_count=affected_count,
                created_by=int(current_user.user_id),
            )
        result = await qa_config_db.get_version(db, id=version_id)
        await qa_config_db.insert_audit(
            db,
            kb_id=kb_id,
            config_version_id=version_id,
            action="save_draft",
            actor_id=int(current_user.user_id),
            before_json=(current_version or {}).get("config_json") or {},
            after_json=summary,
            result="success",
        )
    if result is None:
        raise BusiException("配置草稿保存失败")
    return result


async def _create_reindex_version(
    db,
    kb_id: int,
    config_version_id: int,
) -> dict[str, Any]:
    generation_no = await index_version_db.next_generation(db, kb_id)
    generation = f"generation-{generation_no:03d}"
    index_version_id = await index_version_db.insert_(
        db,
        kb_id=kb_id,
        generation=generation,
        config_version_id=config_version_id,
        status="building",
        vector_collection=f"kb_{kb_id}_{generation.replace('-', '_')}",
    )
    documents = await document_db.list(db, kb_id=kb_id, status__ne=STATUS_DELETED)
    for document in documents:
        await indexing_task_db.insert_(
            db,
            document_id=document["id"],
            kb_id=kb_id,
            config_version_id=config_version_id,
            index_version_id=index_version_id,
            task_type="index",
            status="pending",
        )
    if not documents:
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
            id=kb_id,
        )
    return await index_version_db.get(db, id=index_version_id)


@check_db_connected
async def publish(
    kb_id: int,
    current_user: CurrentUser,
    base_version: int | None = None,
) -> dict[str, Any]:
    await _require_edit_permission(current_user)
    db = DB.get()
    await _get_kb(db, kb_id, current_user)
    async with db.transaction():
        draft = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_DRAFT)
        if draft is None:
            raise BusiException("没有可发布的配置草稿")
        if base_version is not None and draft["version_no"] != base_version:
            raise BusiException("配置版本已变化，请重新加载后再发布", status_code=409)
        published = await qa_config_db.get_version(db, kb_id=kb_id, status=CONFIG_PUBLISHED)
        if published:
            await qa_config_db.update_version(
                db,
                {"status": CONFIG_ARCHIVED, "updated_at": common_utils.utc_now()},
                id=published["id"],
            )
        await qa_config_db.update_version(
            db,
            {
                "status": CONFIG_PUBLISHED,
                "published_by": int(current_user.user_id),
                "published_at": common_utils.utc_now(),
                "updated_at": common_utils.utc_now(),
            },
            id=draft["id"],
        )
        index_version = None
        if draft.get("requires_reindex"):
            index_version = await _create_reindex_version(db, kb_id, draft["id"])
        result = await qa_config_db.get_version(db, id=draft["id"])
        await qa_config_db.insert_audit(
            db,
            kb_id=kb_id,
            config_version_id=draft["id"],
            action="publish",
            actor_id=int(current_user.user_id),
            before_json=(published or {}).get("config_json") or {},
            after_json=draft.get("change_summary_json") or {},
            result="success",
        )
    if result is None:
        raise BusiException("配置发布失败")
    result["index_version"] = index_version
    return result


@check_db_connected
async def reset_to_default(kb_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await _require_edit_permission(current_user)
    db = DB.get()
    knowledge_base = await _get_kb(db, kb_id, current_user)
    return await save_draft(
        kb_id,
        default_config(knowledge_base.get("system_prompt") or ""),
        current_user,
    )


async def _test_config(
    db,
    kb_id: int,
    current_user: CurrentUser,
    config: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    await _require_edit_permission(current_user)
    knowledge_base = await _get_kb(db, kb_id, current_user)
    effective = await get_effective_config(
        db,
        kb_id,
        knowledge_base.get("system_prompt") or "",
    )
    merged = _merge_config(effective, config or {})
    validate_config(merged)
    return knowledge_base, merged


@check_db_connected
async def test_retrieval(
    kb_id: int,
    question: str,
    current_user: CurrentUser,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = DB.get()
    knowledge_base, effective = await _test_config(db, kb_id, current_user, config)
    active_index_version_id = knowledge_base.get("active_index_version_id")
    started_at = perf_counter()
    result = await retrieval_service.search(
        kb_id,
        question,
        config=effective,
        index_version_id=active_index_version_id,
    )
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    return {
        "elapsed_ms": elapsed_ms,
        "retrieval": result.model_dump(),
    }


@check_db_connected
async def test_rerank(
    kb_id: int,
    question: str,
    current_user: CurrentUser,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = DB.get()
    _, effective = await _test_config(db, kb_id, current_user, config)
    rerank_config = effective["rerank"]
    model = rerank_config.get("model") or str(CONF.rag.rerank_model)
    chunks = [
        {
            "id": index,
            "content": content,
            "score": 0.0,
        }
        for index, content in enumerate(
            (
                "这是用于验证重排服务连通性的测试资料。",
                "这是用于验证问答配置的重排模型测试资料。",
                "这是一个与当前问题相关性较低的测试资料。",
            ),
            start=1,
        )
    ]
    started_at = perf_counter()
    results = await rerank(
        question.strip(),
        chunks,
        limit=min(3, int(rerank_config["final_return_count"])),
        model=model,
        timeout_seconds=rerank_config["timeout_seconds"],
    )
    return {
        "success": True,
        "model": model,
        "elapsed_ms": int((perf_counter() - started_at) * 1000),
        "result_count": len(results),
        "top_score": results[0].get("score") if results else None,
    }


@check_db_connected
async def preview_prompt(
    kb_id: int,
    question: str,
    current_user: CurrentUser,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = DB.get()
    _, effective = await _test_config(db, kb_id, current_user, config)
    prompt = str(effective["answer"]["prompt"])
    preview = f"{prompt}\n\n用户问题：{question.strip()}"
    return {
        "question": question.strip(),
        "prompt": preview,
        "character_count": len(preview),
    }


__all__ = (
    "default_config",
    "get_effective_config",
    "get_config",
    "preview_prompt",
    "publish",
    "reset_to_default",
    "save_draft",
    "test_rerank",
    "test_retrieval",
    "validate_config",
)
