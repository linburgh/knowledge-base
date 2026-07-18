from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.config import CONF
from app.core.common.exception import BusiException

EMBEDDING_BATCH_SIZE = 10


def _get_embeddings(model: str) -> OpenAIEmbeddings:
    """根据模型名称创建 Embedding 客户端。

    这里统一读取全局模型配置，屏蔽底层使用的 OpenAI-compatible 接口细节。
    文档分块入库和用户问题检索都会通过这个客户端生成向量。
    """
    if not model:
        raise BusiException("Embedding 模型不能为空")

    return OpenAIEmbeddings(
        model=model,
        api_key=CONF.embedding.api_key,
        base_url=CONF.embedding.base_url,
        timeout=CONF.embedding.timeout_seconds,
        # DashScope Qwen Embedding 单次最多接收 10 条文本，避免大文档批量请求失败。
        chunk_size=EMBEDDING_BATCH_SIZE,
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
) -> list[dict[str, Any]]:
    """为文档分块生成向量，并把向量信息附加到分块副本上。

    方法不会修改调用方传入的原始字典；返回值中的 ``embedding`` 和
    ``embedding_model`` 会在后续入库阶段写入 ``t_document_chunk``。
    """
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
