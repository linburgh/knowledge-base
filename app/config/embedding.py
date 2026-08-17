from __future__ import annotations

from pydantic import StrictInt, StrictStr

from app.config.base import Opt

model = Opt(
    name="model",
    description="Embedding model name",
    schema=StrictStr,
    default="text-embedding-3-small",
)

api_key = Opt(
    name="api_key",
    description="Embedding model API key",
    schema=StrictStr,
    default="change-me",
)

base_url = Opt(
    name="base_url",
    description="Embedding model OpenAI-compatible base URL",
    schema=StrictStr,
    default="http://127.0.0.1:8000/v1",
)

timeout_seconds = Opt(
    name="timeout_seconds",
    description="Embedding model timeout seconds",
    schema=StrictInt,
    default=30,
)

batch_size = Opt(
    name="batch_size",
    description="Embedding request batch size",
    schema=StrictInt,
    default=10,
)

concurrency = Opt(
    name="concurrency",
    description="Maximum concurrent embedding requests",
    schema=StrictInt,
    default=4,
)

retry_count = Opt(
    name="retry_count",
    description="Embedding request retry count",
    schema=StrictInt,
    default=2,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (model, api_key, base_url, timeout_seconds, batch_size, concurrency, retry_count)

__all__ = ("GROUP_NAME", "ALL_OPTS")
