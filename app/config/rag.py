from __future__ import annotations

from pydantic import StrictBool, StrictInt, StrictStr

from app.config.base import Opt

chunk_size = Opt("chunk_size", "Default document chunk size", StrictInt, 600)
chunk_overlap = Opt("chunk_overlap", "Document chunk overlap", StrictInt, 100)
retrieval_top_k = Opt("retrieval_top_k", "Default retrieval top-k", StrictInt, 5)
rerank_enabled = Opt("rerank_enabled", "Enable model reranking", StrictBool, False)
rerank_model = Opt(
    "rerank_model",
    "Reranking model name",
    StrictStr,
    "hans-tech/bge-reranker-v2-m3:260522",
)
rerank_base_url = Opt(
    "rerank_base_url",
    "Reranking service base URL",
    StrictStr,
    "http://127.0.0.1:11434",
)
rerank_endpoint = Opt("rerank_endpoint", "Reranking service endpoint", StrictStr, "/api/rerank")
rerank_api_key = Opt("rerank_api_key", "Reranking service API key", StrictStr, "ollama")
rerank_timeout_seconds = Opt(
    "rerank_timeout_seconds",
    "Reranking request timeout seconds",
    StrictInt,
    30,
)
rerank_fail_open = Opt(
    "rerank_fail_open",
    "Return vector candidates when reranking is unavailable",
    StrictBool,
    True,
)
rerank_candidate_multiplier = Opt(
    "rerank_candidate_multiplier",
    "Number of vector candidates per requested result",
    StrictInt,
    3,
)
max_context_length = Opt("max_context_length", "Maximum context length", StrictInt, 8000)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    chunk_size,
    chunk_overlap,
    retrieval_top_k,
    rerank_enabled,
    rerank_model,
    rerank_base_url,
    rerank_endpoint,
    rerank_api_key,
    rerank_timeout_seconds,
    rerank_fail_open,
    rerank_candidate_multiplier,
    max_context_length,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
