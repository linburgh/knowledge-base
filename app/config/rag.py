from __future__ import annotations

from pydantic import StrictBool, StrictInt

from app.config.base import Opt

chunk_size = Opt("chunk_size", "Default document chunk size", StrictInt, 600)
chunk_overlap = Opt("chunk_overlap", "Document chunk overlap", StrictInt, 100)
retrieval_top_k = Opt("retrieval_top_k", "Default retrieval top-k", StrictInt, 5)
rerank_enabled = Opt("rerank_enabled", "Enable lexical reranking", StrictBool, False)
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
    rerank_candidate_multiplier,
    max_context_length,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
