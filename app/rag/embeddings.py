from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.config import CONF
from app.core.common.exception import BusiException

ProgressCallback = Callable[[int, int], Awaitable[None]]
DEFAULT_BATCH_SIZE = 10


def _get_embeddings(model: str) -> OpenAIEmbeddings:
    """根据模型名称创建 Embedding 客户端。

    这里统一读取全局模型配置，屏蔽底层使用的 OpenAI-compatible 接口细节。
    文档分块入库和用户问题检索都会通过这个客户端生成向量。
    """
    if not model:
        raise BusiException("Embedding 模型不能为空")

    embedding_config = getattr(CONF, "embedding", None)
    configured_batch_size = getattr(embedding_config, "batch_size", DEFAULT_BATCH_SIZE)
    return OpenAIEmbeddings(
        model=model,
        api_key=CONF.embedding.api_key,
        base_url=CONF.embedding.base_url,
        timeout=CONF.embedding.timeout_seconds,
        # DashScope Qwen Embedding 单次最多接收 10 条文本，避免大文档批量请求失败。
        chunk_size=max(1, int(configured_batch_size)),
        # DashScope 兼容接口要求 input 为文本，不能接收 LangChain 默认生成的 token ID。
        check_embedding_ctx_length=False,
    )


async def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    """批量把文本转换为向量。

    文档入库时传入多个分块内容，检索时通常只传入一个用户问题。
    返回结果顺序与输入文本保持一致，便于调用方将向量对应回原始数据。
    """
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
    batch_size: int | None = None,
    concurrency: int | None = None,
    retry_count: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """为文档分块生成向量，并把向量信息附加到分块副本上。

    方法不会修改调用方传入的原始字典；返回值中的 ``embedding`` 和
    ``embedding_model`` 会在后续入库阶段写入 ``t_document_chunk``。
    """
    texts = [chunk.get("content") or "" for chunk in chunks]
    embedding_config = getattr(CONF, "embedding", None)
    configured_batch_size = getattr(embedding_config, "batch_size", DEFAULT_BATCH_SIZE)
    configured_concurrency = getattr(embedding_config, "concurrency", 1)
    configured_retries = getattr(embedding_config, "retry_count", 0)
    effective_batch_size = max(
        1,
        int(configured_batch_size if batch_size is None else batch_size),
    )
    effective_concurrency = max(
        1,
        int(configured_concurrency if concurrency is None else concurrency),
    )
    effective_retries = max(
        0,
        int(configured_retries if retry_count is None else retry_count),
    )
    batches = [
        texts[start : start + effective_batch_size]
        for start in range(0, len(texts), effective_batch_size)
    ]
    semaphore = asyncio.Semaphore(effective_concurrency)
    completed = 0
    completed_lock = asyncio.Lock()

    async def embed_batch(batch: list[str]) -> list[list[float]]:
        nonlocal completed
        async with semaphore:
            last_error: Exception | None = None
            for attempt in range(effective_retries + 1):
                try:
                    vectors = await embed_texts(batch, model)
                    async with completed_lock:
                        completed += len(batch)
                        if progress_callback is not None:
                            await progress_callback(completed, len(texts))
                    return vectors
                except Exception as exc:
                    last_error = exc
                    if attempt < effective_retries:
                        await asyncio.sleep(min(2**attempt, 8))
            assert last_error is not None
            raise last_error

    vector_batches = await asyncio.gather(*(embed_batch(batch) for batch in batches))
    vectors = [vector for batch in vector_batches for vector in batch]
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
