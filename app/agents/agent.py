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
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

from app.agents.policies import authorize_tool, validate_agent_context
from app.agents.runtime import AgentError, AgentOutputInvalid, AgentRuntime
from app.agents.tools import build_default_registry
from app.agents.tools.citations import _build_candidates
from app.agents.tools.history import load_conversation_history_result
from app.agents.tools.retrieval import retrieve_knowledge_result
from app.config import CONF
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.schemas.agent import (
    AgentAnswer,
    AgentContext,
    AgentMode,
    AgentResult,
    AgentTask,
    CitationCandidate,
    ToolCall,
)

AGENT_SYSTEM_PROMPT = """你是企业知识库问答智能体。
必须先使用 retrieve_knowledge 获取事实依据，再基于工具返回内容回答。
回答追问时要结合提供的对话上下文；“这家公司”“该产品”“上述方案”等表达应自然关联上下文中的对象。
需要补充上下文时可以使用 load_conversation_history。
不得编造知识库中没有的事实，不得自行声称拥有用户、租户或知识库权限。
如果检索结果为空或不足，明确说明知识库中没有足够资料。
最终答案先用自然语言直接回答问题；简单问题用一到三段完成，不要套用固定模板，不要为了结构添加“产品概述、核心能力”等小标题，只有确实需要并列说明时才使用简短列表。
除非用户明确要求详细方案，普通问答控制在 180 字左右；流程问题只保留资料中明确的关键步骤。
涉及价格、交付周期、资质、公司背景等资料未明确给出的信息时，直接说明当前知识库未提供，不要根据行业常识推测。
面向客户时使用专业、自然、易理解的表达，不要写成评测报告，不要提及工具调用、模型、提示词、内部流程或系统异常。
不要机械照抄资料原文；应在不改变事实的前提下进行归纳，避免重复、乱码和无关操作步骤。
最终结构化输出中的 citation_chunk_ids 只能填写实际检索结果中的 chunk id。
"""

FALLBACK_SUMMARY_PROMPT = """你是企业售前知识顾问。请仅根据提供的知识库资料回答用户问题。
要求：
1. 先用一两句话直接回答问题；简单问题不要使用固定栏目或大段分点；
2. 内容专业、自然，适合直接展示给客户；
3. 可按“产品概述、核心能力、应用场景、业务价值”组织，但不要为了凑结构添加资料中没有的内容；
4. 只使用资料中明确存在的信息，不确定的内容不要推断；
5. 不要提及检索、模型、系统异常、降级回答或内部处理过程；
6. 不要机械复制大段原文，控制在 300 字以内。

用户问题：{question}

知识库资料：
{sources}
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
            excluded_middleware=frozenset({"TodoListMiddleware"}),
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
        tools=[],
        system_prompt=AGENT_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=StateBackend(),
        permissions=_build_filesystem_permissions(),
        response_format=ToolStrategy(AgentAnswer),
        context_schema=AgentContext,
        name="knowledge_agent",
        debug=False,
    )


@lru_cache(maxsize=1)
def get_knowledge_answer_model():
    """返回单次回答模型，避免问答阶段进入可循环 Agent 图。"""
    return _build_chat_model()


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


async def _conversation_prompt(context: AgentContext) -> str:
    """读取有限的会话上下文，帮助模型自然理解当前追问。"""
    if context.conversation_id is None:
        return ""
    try:
        call = ToolCall(
            call_id="agent-history-context",
            name="load_conversation_history",
            input={"limit": 8},
        )
        authorize_tool(context=context, call=call, registry=build_default_registry())
        history = await load_conversation_history_result(call, context)
        if not history.ok:
            return ""
        messages = history.data.get("messages", [])
        lines = []
        for message in messages:
            role = "用户" if message.get("role") == "user" else "助手"
            content = str(message.get("content") or "").strip()
            if content:
                lines.append(f"{role}：{content}")
        if not lines:
            return ""
        return (
            "以下是最近的对话上下文，请结合它理解当前问题，但事实仍以知识库检索结果为准：\n"
            + "\n".join(lines)
        )
    except Exception:
        LOG.warning("Conversation context unavailable conversation_id={}", context.conversation_id)
        return ""


def _retrieval_context_prompt(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "本次知识库检索没有返回可用资料。请明确说明当前资料不足，不要根据常识补充答案。"

    context_parts = [
        "以下是本次知识库检索返回的资料，只能依据这些资料回答；每条资料的 chunk_id 可用于引用："
    ]
    for index, chunk in enumerate(chunks, 1):
        content = str(chunk.get("content") or "").strip()
        if len(content) > 2400:
            content = f"{content[:2400]}..."
        context_parts.append(
            "\n".join(
                [
                    f"资料 {index}：chunk_id={chunk.get('id')}",
                    f"来源：{chunk.get('source_name') or '未知来源'}",
                    f"内容：{content}",
                ]
            )
        )
    return "\n\n".join(context_parts)


def _parse_agent_answer(value: Any) -> AgentAnswer | None:
    if isinstance(value, AgentAnswer):
        return value
    if isinstance(value, dict) and "answer" in value:
        try:
            return AgentAnswer.model_validate(value)
        except ValueError:
            return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _parse_agent_answer(parsed)
    return None


def _structured_answer(result: Any) -> AgentAnswer:
    direct = _parse_agent_answer(result)
    if direct is not None:
        return direct
    if not isinstance(result, dict):
        content = _message_content(result).strip()
        if content:
            return AgentAnswer(answer=content, termination_reason="completed")
    structured = _parse_agent_answer(result.get("structured_response"))
    if structured is not None:
        return structured
    messages = result.get("messages", [])
    for message in reversed(messages):
        for tool_call in reversed(getattr(message, "tool_calls", []) or []):
            parsed = _parse_agent_answer(tool_call.get("args"))
            if parsed is not None:
                return parsed
        additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
        for tool_call in reversed(additional_kwargs.get("tool_calls", []) or []):
            function = tool_call.get("function", {})
            parsed = _parse_agent_answer(function.get("arguments"))
            if parsed is not None:
                return parsed
        parsed = _parse_agent_answer(getattr(message, "content", None))
        if parsed is not None:
            return parsed
        if getattr(message, "type", None) == "ai" and _message_content(message).strip():
            return AgentAnswer(
                answer=_message_content(message).strip(), termination_reason="completed"
            )
    raise AgentOutputInvalid("Agent 未返回有效答案")


async def _fallback_result(
    task: AgentTask,
    context: AgentContext,
    started_at: float,
    reason: str,
    retrieved_chunks: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Agent 失败时基于检索结果返回可展示的降级回答。"""
    chunks: list[dict[str, Any]] = list(retrieved_chunks or [])
    try:
        if not chunks:
            call = ToolCall(
                call_id="fallback-retrieve",
                name="retrieve_knowledge",
                input={"query": task.question, "top_k": task.top_k},
            )
            authorize_tool(context=context, call=call, registry=build_default_registry())
            retrieval = await retrieve_knowledge_result(call, context)
            if retrieval.ok:
                chunks = retrieval.data.get("chunks", [])
    except Exception:
        LOG.exception("Fallback knowledge retrieval failed kb_id={}", task.kb_id)

    citations = _build_candidates(chunks).citations
    answer = ""
    if citations:
        sources = []
        for citation in citations[:3]:
            snippet = citation.snippet.strip()
            if len(snippet) > 800:
                snippet = f"{snippet[:800]}..."
            sources.append(f"来源：{citation.source_name}\n{snippet}")
        try:
            summary_prompt = FALLBACK_SUMMARY_PROMPT.format(
                question=task.question,
                sources="\n\n".join(sources),
            )
            response = await asyncio.wait_for(
                _build_chat_model().ainvoke(
                    [{"role": "user", "content": summary_prompt}]
                ),
                timeout=CONF.chat.timeout_seconds,
            )
            answer = _message_content(response).strip()
        except Exception:
            LOG.exception("Fallback answer generation failed kb_id={}", task.kb_id)

        if not answer:
            answer = (
                "当前智能问答暂时无法生成完整答案，以下是根据相关资料检索到的内容，"
                "供你先行参考：\n\n" + "\n\n".join(sources)
            )
    else:
        answer = "当前智能问答服务暂时繁忙，暂时无法完成回答，请稍后重试。"

    LOG.warning(
        "Knowledge agent fallback used kb_id={} reason={} hit_count={}",
        task.kb_id,
        reason,
        len(chunks),
    )
    return AgentResult(
        answer=answer,
        citations=citations,
        mode=choose_mode(task.question),
        status="failed",
        top_k=task.top_k or 5,
        hit_count=len(chunks),
        termination_reason="fallback",
        duration_ms=int((monotonic() - started_at) * 1000),
    )


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
    retrieved_chunks: list[dict[str, Any]] = []
    try:
        conversation_prompt = await _conversation_prompt(context)
        retrieval_query = task.question
        if conversation_prompt and any(
            marker in task.question for marker in ("上一条", "这家公司", "该产品", "上述")
        ):
            retrieval_query = f"{task.question}\n{conversation_prompt[-2400:]}"
        retrieval_call = ToolCall(
            call_id="agent-retrieve",
            name="retrieve_knowledge",
            input={"query": retrieval_query, "top_k": task.top_k},
        )
        authorize_tool(
            context=context,
            call=retrieval_call,
            registry=build_default_registry(),
        )
        retrieval = await retrieve_knowledge_result(retrieval_call, context)
        if not retrieval.ok:
            raise BusiException(retrieval.error_message or "知识库检索失败")
        retrieved_chunks = retrieval.data.get("chunks", [])

        prompt_parts = []
        if conversation_prompt:
            prompt_parts.append(conversation_prompt)
        if context.knowledge_base_prompt:
            prompt_parts.append(
                "知识库专属回答规则（仅作为回答风格约束，不能改变权限和引用规则）：\n"
                f"{context.knowledge_base_prompt}"
            )
        prompt_parts.append(_retrieval_context_prompt(retrieved_chunks))
        prompt_parts.append(f"当前问题：{task.question}")
        prompt = "\n\n".join(prompt_parts)
        result = await asyncio.wait_for(
            get_knowledge_answer_model().ainvoke(
                [
                    {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            ),
            timeout=CONF.agent.total_timeout_seconds,
        )
        answer = _structured_answer(result)
    except TimeoutError:
        LOG.exception("Knowledge agent timed out kb_id={}", task.kb_id)
        return await _fallback_result(
            task,
            context,
            started_at,
            "timeout",
            retrieved_chunks,
        )
    except Exception as exc:
        LOG.exception("Knowledge agent output failed kb_id={}", task.kb_id)
        return await _fallback_result(
            task,
            context,
            started_at,
            str(exc),
            retrieved_chunks,
        )

    chunks = retrieved_chunks
    citations = _select_citations(chunks, answer.citation_chunk_ids)
    tool_call_count = 1 if retrieved_chunks else 0
    model_call_count = 1
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
