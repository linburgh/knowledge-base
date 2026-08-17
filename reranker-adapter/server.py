"""Local-only FastAPI server adapting Ollama generate to a rerank protocol."""

import asyncio
import logging
import time

import httpx
from fastapi import FastAPI, HTTPException

from config import settings
from ollama_client import OllamaUnavailableError, score_document
from schemas import HealthResponse, RerankRequest, RerankResponse, RerankResult


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Local Ollama Reranker Adapter", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        ollama_base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )


@app.post("/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest) -> RerankResponse:
    if len(request.documents) > settings.max_documents:
        raise HTTPException(
            status_code=400,
            detail=f"候选文档数量不能超过 {settings.max_documents}",
        )

    top_n = request.top_n or len(request.documents)
    if top_n > len(request.documents):
        raise HTTPException(status_code=400, detail="top_n 不能大于候选文档数量")

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            scored = await asyncio.gather(
                *(
                    score_document(client, settings, request.query, document)
                    for document in request.documents
                )
            )
    except OllamaUnavailableError as exc:
        logger.exception("Ollama rerank failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected rerank adapter error")
        raise HTTPException(status_code=500, detail="重排适配器执行失败") from exc

    results = sorted(
        (
            RerankResult(index=index, relevance_score=score)
            for index, (score, _) in enumerate(scored)
        ),
        key=lambda item: item.relevance_score,
        reverse=True,
    )[:top_n]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(
        "rerank completed query_length=%s documents=%s elapsed_ms=%s",
        len(request.query),
        len(request.documents),
        elapsed_ms,
    )
    return RerankResponse(
        results=results,
        model=settings.ollama_model,
        elapsed_ms=elapsed_ms,
    )
