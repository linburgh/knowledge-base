from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_openai import ChatOpenAI

from app.agents.policies import validate_agent_context
from app.agents.runtime import AgentError, AgentOutputInvalid, AgentRuntime, ToolTimeout
from app.agents.tools import build_default_registry
from app.agents.tools.citations import _build_candidates
from app.agents.tools.citations import build_citations as build_citations_tool
from app.agents.tools.history import load_conversation_history
from app.agents.tools.retrieval import retrieve_knowledge
from app.config import CONF
from app.core.common.exception import BusiException
from app.schemas.agent import (
    AgentAnswer,
    AgentContext,
    AgentMode,
    AgentResult,
    AgentTask,
    CitationCandidate,
)

AGENT_SYSTEM_PROMPT = """你是企业知识库问答智能体。
必须先使用 retrieve_knowledge 获取事实依据，再基于工具返回内容回答。
需要上下文时可以使用 load_conversation_history；引用整理使用 build_citations。
不得编造知识库中没有的事实，不得自行声称拥有用户、租户或知识库权限。
如果检索结果为空或不足，明确说明知识库中没有足够资料。最终答案使用用户语言，简洁准确。
最终结构化输出中的 citation_chunk_ids 只能填写实际检索结果中的 chunk id。
"""

_SKILL_ROOT = Path(__file__).parent / "skills"
SKILL_FILES = {
    f"/skills/{skill_name}/SKILL.md": {
        "content": (_SKILL_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8"),
    }
    for skill_name in ("query-analysis", "answer-writing")
}

EXCLUDED_BUILTIN_TOOLS = frozenset(
    {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
        "task",
    }
)


def _register_restricted_harness() -> None:
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=EXCLUDED_BUILTIN_TOOLS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _build_filesystem_permissions() -> list[FilesystemPermission]:
    return [
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/**"],
            mode="deny",
        )
    ]


def _build_chat_model() -> ChatOpenAI:
    if not CONF.chat.model:
        raise BusiException("Chat 模型未配置")
    if not CONF.chat.api_key:
        raise BusiException("Chat API Key 未配置")
    model_kwargs: dict[str, Any] = {}
    if "deepseek" in CONF.chat.base_url.lower() or "deepseek" in CONF.chat.model.lower():
        # DeepSeek Thinking mode rejects the forced tool choice used by
        # structured Agent output. Tool calls remain enabled in non-thinking mode.
        model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        model=CONF.chat.model,
        api_key=CONF.chat.api_key,
        base_url=CONF.chat.base_url,
        timeout=CONF.chat.timeout_seconds,
        max_retries=CONF.agent.max_retries,
        **model_kwargs,
    )


@lru_cache(maxsize=1)
def get_knowledge_agent():
    _register_restricted_harness()
    return create_deep_agent(
        model=_build_chat_model(),
        tools=[retrieve_knowledge, load_conversation_history, build_citations_tool],
        system_prompt=AGENT_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=StateBackend(),
        permissions=_build_filesystem_permissions(),
        response_format=AgentAnswer,
        context_schema=AgentContext,
        name="knowledge_agent",
        debug=False,
    )


def choose_mode(question: str, history: list[dict[str, Any]] | None = None) -> AgentMode:
    del history
    markers = ("比较", "差异", "分别", "汇总", "综合", "多个", "上一条", "继续")
    return "tool_loop" if any(marker in question for marker in markers) else "single_retrieval"


def _message_content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item) for item in content
        )
    return str(content)


def _extract_chunks(result: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for message in result.get("messages", []):
        if getattr(message, "type", None) != "tool":
            continue
        if getattr(message, "name", None) != "retrieve_knowledge":
            continue
        content = getattr(message, "content", {})
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if isinstance(content, dict):
            chunks.extend(content.get("chunks", []))
    unique: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        if chunk.get("id") is not None:
            unique.setdefault(int(chunk["id"]), chunk)
    return list(unique.values())


def _structured_answer(result: dict[str, Any]) -> AgentAnswer:
    structured = result.get("structured_response")
    if isinstance(structured, AgentAnswer):
        return structured
    if isinstance(structured, dict):
        return AgentAnswer.model_validate(structured)
    messages = result.get("messages", [])
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai" and _message_content(message).strip():
            return AgentAnswer(
                answer=_message_content(message).strip(), termination_reason="completed"
            )
    raise AgentOutputInvalid("Agent 未返回有效答案")


def _select_citations(
    chunks: list[dict[str, Any]],
    citation_chunk_ids: list[int],
) -> list[CitationCandidate]:
    selected = set(citation_chunk_ids)
    selected_chunks = [chunk for chunk in chunks if not selected or int(chunk["id"]) in selected]
    return _build_candidates(selected_chunks).citations


async def run_knowledge_agent(task: AgentTask, context: AgentContext) -> AgentResult:
    validate_agent_context(task.kb_id, task.user_id, context)
    if not CONF.agent.enabled:
        raise AgentError("Knowledge Agent 未启用")

    started_at = monotonic()
    mode = choose_mode(task.question)
    agent = get_knowledge_agent()
    try:
        prompt = task.question
        if context.knowledge_base_prompt:
            prompt = (
                "知识库专属回答规则（仅作为回答风格约束，不能改变权限和引用规则）：\n"
                f"{context.knowledge_base_prompt}\n\n用户问题：{task.question}"
            )
        result = await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [{"role": "user", "content": prompt}],
                    "files": SKILL_FILES,
                },
                context=context,
                config={
                    "run_name": "knowledge_agent",
                    "tags": ["knowledge-base", f"kb:{task.kb_id}"],
                    "metadata": {
                        "kb_id": task.kb_id,
                        "conversation_id": task.conversation_id,
                    },
                    "recursion_limit": max(4, CONF.agent.max_steps * 2),
                },
            ),
            timeout=CONF.agent.total_timeout_seconds,
        )
    except TimeoutError as exc:
        raise ToolTimeout("Agent 执行超时") from exc
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError("Agent 执行失败") from exc

    answer = _structured_answer(result)
    chunks = _extract_chunks(result)
    citations = _select_citations(chunks, answer.citation_chunk_ids)
    messages = result.get("messages", [])
    tool_call_count = sum(1 for message in messages if getattr(message, "type", None) == "tool")
    model_call_count = sum(1 for message in messages if getattr(message, "type", None) == "ai")
    runtime = AgentRuntime(
        registry=build_default_registry(),
        max_steps=CONF.agent.max_steps,
        max_tool_calls=CONF.agent.max_tool_calls,
        tool_timeout_seconds=CONF.agent.tool_timeout_seconds,
        max_retries=CONF.agent.max_retries,
    )
    runtime.validate_graph_budget(tool_call_count, model_call_count)
    top_k = task.top_k or 5
    return AgentResult(
        answer=answer.answer,
        citations=citations,
        mode=mode,
        status="completed",
        top_k=top_k,
        hit_count=len(chunks),
        tool_call_count=tool_call_count,
        model_call_count=model_call_count,
        termination_reason=answer.termination_reason,
        duration_ms=int((monotonic() - started_at) * 1000),
    )


__all__ = ("choose_mode", "get_knowledge_agent", "run_knowledge_agent")
