from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.config import CONF
from app.core.common.exception import BusiException


def _get_embeddings(model: str) -> OpenAIEmbeddings:
    if not model:
        raise BusiException("Embedding 模型不能为空")

    return OpenAIEmbeddings(
        model=model,
        api_key=CONF.model.api_key,
        base_url=CONF.model.base_url,
        timeout=CONF.model.timeout_seconds,
    )


async def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    if not texts:
        return []

    try:
        return await _get_embeddings(model).aembed_documents(texts)
    except BusiException:
        raise
    except Exception as exc:
        raise BusiException("Embedding 生成失败") from exc


async def embed_chunks(
    chunks: list[dict[str, Any]],
    model: str,
) -> list[dict[str, Any]]:
    texts = [chunk.get("content") or "" for chunk in chunks]
    vectors = await embed_texts(texts, model)
    if len(vectors) != len(chunks):
        raise BusiException("Embedding 生成结果数量不匹配")

    embedded_chunks = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        item = dict(chunk)
        item["embedding"] = vector
        item["embedding_model"] = model
        embedded_chunks.append(item)
    return embedded_chunks


__all__ = ("embed_chunks", "embed_texts")
