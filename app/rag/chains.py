from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from app.config import CONF
from app.core.common.exception import BusiException

DEFAULT_SYSTEM_PROMPT = """你是企业知识库问答助手。
请只根据给定的知识库上下文回答问题，不要补充上下文中没有依据的事实。
如果上下文不足以回答问题，请明确说明当前资料不足。
回答应简洁、准确，必要时引用文档名称和页码。
"""


def _format_context(chunks: list[dict[str, Any]]) -> str:
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        page = chunk.get("page")
        page_text = f"第 {page} 页" if page is not None else "未提供页码"
        blocks.append(
            f"[资料 {index}]\n"
            f"文档：{chunk.get('source_name') or '未命名文档'}\n"
            f"页码：{page_text}\n"
            f"内容：\n{chunk.get('content') or ''}"
        )
    return "\n\n".join(blocks)


def _message_content(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        values = []
        for block in content:
            if isinstance(block, str):
                values.append(block)
            elif isinstance(block, dict) and block.get("text"):
                values.append(str(block["text"]))
        return "".join(values).strip()
    return str(content).strip()


async def generate_answer(
    question: str,
    chunks: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> str:
    """将知识库提示词、检索分块组装成上下文并调用聊天模型生成答案。"""
    if not chunks:
        return "当前知识库暂无可用内容，暂时无法回答这个问题。"
    if not CONF.chat.model:
        raise BusiException("Chat 模型未配置")

    context = _format_context(chunks)
    prompt = (
        f"{DEFAULT_SYSTEM_PROMPT}\n\n"
        f"知识库补充指令：\n{system_prompt.strip() if system_prompt and system_prompt.strip() else '无'}\n\n"
        f"知识库上下文：\n{context}\n\n"
        f"用户问题：{question}\n\n"
        "请基于上述上下文回答用户问题。"
    )
    try:
        model = ChatOpenAI(
            model=CONF.chat.model,
            api_key=CONF.chat.api_key,
            base_url=CONF.chat.base_url,
            timeout=CONF.chat.timeout_seconds,
        )
        result = await model.ainvoke(prompt)
        answer = _message_content(result)
    except BusiException:
        raise
    except Exception as exc:
        raise BusiException("Chat 模型调用失败") from exc

    if not answer:
        raise BusiException("Chat 模型返回内容为空")
    return answer


__all__ = ("generate_answer",)
