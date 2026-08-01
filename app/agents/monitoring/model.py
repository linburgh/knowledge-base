from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from app.config import CONF
from app.core.common.exception import BusiException


def build_monitoring_chat_model() -> ChatOpenAI:
    if not CONF.chat.model:
        raise BusiException("对话模型未配置")
    if not CONF.chat.api_key:
        raise BusiException("对话模型密钥未配置")
    model_kwargs: dict[str, Any] = {}
    if "deepseek" in CONF.chat.base_url.lower() or "deepseek" in CONF.chat.model.lower():
        model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        model=CONF.chat.model,
        api_key=CONF.chat.api_key,
        base_url=CONF.chat.base_url,
        timeout=CONF.chat.timeout_seconds,
        max_retries=CONF.agent.max_retries,
        **model_kwargs,
    )


__all__ = ("build_monitoring_chat_model",)
