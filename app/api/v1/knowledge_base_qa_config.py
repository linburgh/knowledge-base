from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import knowledge_base_qa_config as qa_config_service
from app.schemas.knowledge_base_qa_config import (
    KnowledgeBaseQaConfigDraftRequest,
    KnowledgeBaseQaConfigPromptPreviewResponse,
    KnowledgeBaseQaConfigPublishRequest,
    KnowledgeBaseQaConfigRerankTestResponse,
    KnowledgeBaseQaConfigTestRequest,
)

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


@router.get("/{kb_id}/qa-config")
async def get_config(
    kb_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.get_config(kb_id, current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{kb_id}/qa-config/draft")
async def save_draft(
    kb_id: int,
    payload: KnowledgeBaseQaConfigDraftRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.save_draft(
            kb_id,
            payload.config,
            current_user,
            base_version=payload.base_version,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{kb_id}/qa-config/publish")
async def publish(
    kb_id: int,
    payload: KnowledgeBaseQaConfigPublishRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.publish(
            kb_id,
            current_user,
            base_version=payload.base_version,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{kb_id}/qa-config/save-and-publish")
async def save_and_publish(
    kb_id: int,
    payload: KnowledgeBaseQaConfigDraftRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.save_and_publish(
            kb_id,
            payload.config,
            current_user,
            base_version=payload.base_version,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{kb_id}/qa-config/reset")
async def reset(
    kb_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.reset_to_default(kb_id, current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{kb_id}/qa-config/retrieval-test")
async def retrieval_test(
    kb_id: int,
    payload: KnowledgeBaseQaConfigTestRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.test_retrieval(
            kb_id,
            payload.question,
            current_user,
            payload.config,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post(
    "/{kb_id}/qa-config/rerank-test",
    response_model=KnowledgeBaseQaConfigRerankTestResponse,
)
async def rerank_test(
    kb_id: int,
    payload: KnowledgeBaseQaConfigTestRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.test_rerank(
            kb_id,
            payload.question,
            current_user,
            payload.config,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post(
    "/{kb_id}/qa-config/prompt-preview",
    response_model=KnowledgeBaseQaConfigPromptPreviewResponse,
)
async def prompt_preview(
    kb_id: int,
    payload: KnowledgeBaseQaConfigTestRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await qa_config_service.preview_prompt(
            kb_id,
            payload.question,
            current_user,
            payload.config,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
