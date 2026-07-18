from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import retrieval as retrieval_service
from app.schemas.retrieval import RetrievalRequest

router = APIRouter()


async def _search(payload: RetrievalRequest) -> Any:
    try:
        return await retrieval_service.search(
            kb_id=payload.kb_id,
            query=payload.query,
            top_k=payload.top_k,
            mode=payload.mode,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("", status_code=status.HTTP_200_OK)
async def search(payload: RetrievalRequest) -> Any:
    return await _search(payload)


@router.get("")
async def search_by_query(
    kb_id: int,
    query: str,
    top_k: int | None = None,
    mode: str = "vector",
) -> Any:
    return await _search(
        RetrievalRequest(kb_id=kb_id, query=query, top_k=top_k, mode=mode),
    )


__all__ = ("router",)
