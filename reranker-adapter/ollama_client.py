"""Async Ollama client used by the adapter."""

from typing import Any

import httpx

from config import Settings
from parser import ModelResultError, parse_score
from prompt import build_prompt


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama cannot complete a request."""


async def score_document(
    client: httpx.AsyncClient,
    settings: Settings,
    query: str,
    document: str,
) -> tuple[float, str]:
    payload = {
        "model": settings.ollama_model,
        "prompt": build_prompt(query, document),
        "raw": True,
        "stream": False,
        "logprobs": True,
        "top_logprobs": settings.top_logprobs,
        "options": {"temperature": 0, "num_predict": 1},
    }
    try:
        response = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json=payload,
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("Ollama 重排请求超时") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaUnavailableError(f"Ollama 重排请求失败: {exc}") from exc

    try:
        return parse_score(
            result,
            fallback_binary_score=settings.fallback_binary_score,
        )
    except ModelResultError as exc:
        raise OllamaUnavailableError(str(exc)) from exc
