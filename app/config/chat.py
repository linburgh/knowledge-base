from __future__ import annotations

from pydantic import StrictInt, StrictStr

from app.config.base import Opt

model = Opt(
    name="model",
    description="Chat model name",
    schema=StrictStr,
    default="change-me",
)

api_key = Opt(
    name="api_key",
    description="Chat model API key",
    schema=StrictStr,
    default="change-me",
)

base_url = Opt(
    name="base_url",
    description="Chat model OpenAI-compatible base URL",
    schema=StrictStr,
    default="http://127.0.0.1:8000/v1",
)

timeout_seconds = Opt(
    name="timeout_seconds",
    description="Chat model timeout seconds",
    schema=StrictInt,
    default=30,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (model, api_key, base_url, timeout_seconds)

__all__ = ("GROUP_NAME", "ALL_OPTS")
