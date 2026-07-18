from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import chat as chat_service
from app.schemas.chat import ChatRequest

router = APIRouter()


@router.post("")
async def chat(payload: ChatRequest) -> Any:
    try:
        return await chat_service.chat(
            kb_id=payload.kb_id,
            question=payload.question,
            user_id=payload.user_id,
            conversation_id=payload.conversation_id,
            top_k=payload.top_k,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
