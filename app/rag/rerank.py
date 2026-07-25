from __future__ import annotations

from typing import Any

import httpx

from app.config import CONF
from app.core.common.exception import BusiException


def _endpoint_url() -> str:
    base_url = CONF.rag.rerank_base_url.rstrip("/")
    return f"{base_url}{CONF.rag.rerank_endpoint}"


def _parse_results(payload: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = payload.get("results") or payload.get("data") or []
    if not isinstance(results, list):
        raise BusiException("重排模型返回格式不合法")

    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for fallback_index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        index = result.get("index", result.get("document_index", fallback_index))
        try:
            chunk = chunks[int(index)]
            score = float(
                result.get("relevance_score", result.get("score", result.get("value")))
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise BusiException("重排模型返回结果无法映射文档分块") from exc
        item = dict(chunk)
        item["vector_score"] = float(chunk.get("score") or 0.0)
        item["score"] = score
        ranked.append((score, fallback_index, item))

    if not ranked:
        raise BusiException("重排模型没有返回结果")
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]


async def rerank(
    query: str,
    chunks: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """调用外部重排服务对向量候选集进行二次排序。

    当前配置默认适配 Ollama 的 ``/api/rerank`` 协议；如果 Ollama 前面部署了
    OpenAI-compatible 重排网关，只需替换 base_url 和 endpoint，不需要修改业务代码。
    """
    if not chunks:
        return []
    request = {
        "model": CONF.rag.rerank_model,
        "query": query,
        "documents": [str(chunk.get("content") or "") for chunk in chunks],
        "top_n": limit,
    }
    headers = {"Content-Type": "application/json"}
    if CONF.rag.rerank_api_key:
        headers["Authorization"] = f"Bearer {CONF.rag.rerank_api_key}"
    try:
        async with httpx.AsyncClient(
            timeout=CONF.rag.rerank_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(_endpoint_url(), json=request, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BusiException("重排模型调用失败") from exc
    return _parse_results(payload, chunks)[:limit]


__all__ = ("rerank",)
