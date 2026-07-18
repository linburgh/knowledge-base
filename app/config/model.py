from __future__ import annotations

from pydantic import StrictInt, StrictStr

from app.config.base import Opt

chat_model = Opt(
    name="chat_model",
    description="Chat model name",
    schema=StrictStr,
    default="change-me",
)

embedding_model = Opt(
    name="embedding_model",
    description="Embedding model name",
    schema=StrictStr,
    default="text-embedding-3-small",
)

api_key = Opt(
    name="api_key",
    description="OpenAI-compatible API key",
    schema=StrictStr,
    default="change-me",
)

base_url = Opt(
    name="base_url",
    description="OpenAI-compatible API base URL",
    schema=StrictStr,
    default="http://127.0.0.1:8000/v1",
)

timeout_seconds = Opt(
    name="timeout_seconds",
    description="Model API timeout seconds",
    schema=StrictInt,
    default=30,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    chat_model,
    embedding_model,
    api_key,
    base_url,
    timeout_seconds,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
