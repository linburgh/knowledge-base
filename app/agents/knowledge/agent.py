"""知识库问答 Agent 的创建、执行与结果收敛入口。

本模块组装只读 Deep Agent Harness，将 Service 提供的可信上下文注入工具运行时，
并把模型输出、检索事实与引用轨迹收敛为公开的 ``AgentResult`` 协议。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
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
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

from app.agents.knowledge.policies import validate_agent_context, validate_agent_result
from app.agents.knowledge.runtime import AgentError, AgentOutputInvalid, AgentRuntime, ToolTimeout
from app.agents.knowledge.state import KnowledgeHarnessContext, KnowledgeSession
from app.agents.knowledge.tools import (
    build_citations,
    build_default_registry,
    load_conversation_history,
    retrieve_knowledge,
)
from app.config import CONF
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.core.common.structured_output import repair_structured_output
from app.core.monitoring import emit_gather_event, monitor_gather
from app.schemas.agent import (
    AgentAnswer,
    AgentContext,
    AgentMode,
    AgentResult,
    AgentSkillRef,
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
    """注册禁用写文件、命令执行和子 Agent 的受限 Harness 配置。"""
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=EXCLUDED_BUILTIN_TOOLS,
            excluded_middleware=frozenset({"TodoListMiddleware"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _build_filesystem_permissions() -> list[FilesystemPermission]:
    """仅允许读取注入的 Skill 文件，拒绝其他文件系统操作。"""
    return [
        FilesystemPermission(
            operations=["read"],
            paths=["/skills/**"],
            mode="allow",
        ),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/**"],
            mode="deny",
        ),
    ]


def _build_chat_model() -> ChatOpenAI:
    """按项目配置创建问答模型，并处理供应商工具调用兼容项。"""
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


@lru_cache(maxsize=16)
def get_knowledge_agent(
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
):
    """创建并缓存指定模型、工具预算的知识库 Deep Agent。"""
    _register_restricted_harness()
    model_limit = max_model_calls or CONF.agent.max_steps
    tool_limit = max_tool_calls or CONF.agent.max_tool_calls
    return create_deep_agent(
        model=_build_chat_model(),
        tools=[retrieve_knowledge, load_conversation_history, build_citations],
        system_prompt=AGENT_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=StateBackend(),
        permissions=_build_filesystem_permissions(),
        response_format=ToolStrategy(AgentAnswer),
        context_schema=KnowledgeHarnessContext,
        middleware=[
            # Harness 预算包含 Skill 读取和结构化终态；真实检索、历史、引用工具
            # 另由本次 KnowledgeSession 的 Runtime 按业务预算逐次记账。
            ToolCallLimitMiddleware(
                run_limit=max(model_limit * 4, tool_limit + len(SKILL_FILES) * 2 + 4),
                exit_behavior="error",
            ),
            ModelCallLimitMiddleware(
                run_limit=model_limit,
                exit_behavior="end",
            ),
        ],
        name="knowledge_agent",
        debug=False,
    )


@lru_cache(maxsize=1)
def get_knowledge_answer_model():
    """返回单次回答模型，避免问答阶段进入可循环 Agent 图。"""
    return _build_chat_model()


def choose_mode(question: str, history: list[dict[str, Any]] | None = None) -> AgentMode:
    """根据问题复杂度选择单次检索或多工具循环模式。"""
    del history
    markers = ("比较", "差异", "分别", "汇总", "综合", "多个", "上一条", "继续")
    return "tool_loop" if any(marker in question for marker in markers) else "single_retrieval"


def _message_content(message: Any) -> str:
    """把 LangChain 的多形态消息内容规范化为纯文本。"""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item) for item in content
        )
    return str(content)


def _extract_chunks(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从工具消息中提取并按分块 ID 去重实际检索结果。"""
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


def _skill_refs() -> list[AgentSkillRef]:
    """生成用于审计的 Skill 名称及内容版本摘要。"""
    refs: list[AgentSkillRef] = []
    for path, payload in SKILL_FILES.items():
        content = str(payload["content"])
        refs.append(
            AgentSkillRef(
                name=path.split("/")[-2],
                version=hashlib.sha256(content.encode("utf-8")).hexdigest()[:12],
            )
        )
    return refs


def _skill_prompt() -> str:
    """将受控 Skill 内容拼接为单次回答模型的附加指导。"""
    return "\n\n".join(
        f"技能 {path.split('/')[-2]}：\n{payload['content']}"
        for path, payload in SKILL_FILES.items()
    )


async def _conversation_prompt(context: AgentContext, runtime: AgentRuntime) -> str:
    """读取有限的会话上下文，帮助模型自然理解当前追问。"""
    if context.conversation_id is None:
        return ""
    try:
        call = ToolCall(
            call_id="agent-history-context",
            name="load_conversation_history",
            input={"limit": 8},
        )
        history = await runtime.execute(call, context)
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
    """将检索分块序列化为标明不可信边界的模型上下文。"""
    if not chunks:
        return "本次知识库检索没有返回可用资料。请明确说明当前资料不足，不要根据常识补充答案。"

    context_parts = [
        "以下是本次知识库检索返回的资料，只能依据这些资料回答；每条资料的 chunk_id 可用于引用："
    ]
    total_chars = 0
    for index, chunk in enumerate(chunks[:20], 1):
        content = str(chunk.get("content") or "").strip()
        if len(content) > 2400:
            content = f"{content[:2400]}..."
        if total_chars + len(content) > 30000:
            break
        total_chars += len(content)
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
    """兼容对象、字典与 JSON 文本形式的结构化回答。"""
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
    """从 Deep Agent 结果中提取最终结构化回答。"""
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


async def _repair_knowledge_answer(
    *,
    task: AgentTask,
    chunks: list[dict[str, Any]],
    timeout_seconds: float,
):
    """仅用已检索分块修复问答终态，不在修复轮开放知识库工具。"""

    evidence = [
        {
            "chunk_id": item.get("id"),
            "source_name": item.get("source_name"),
            "content": str(item.get("content") or "")[:2400],
        }
        for item in chunks[:20]
    ]
    return await repair_structured_output(
        model=_build_chat_model(),
        schema=AgentAnswer,
        evidence_payload={"question": task.question, "retrieved_chunks": evidence},
        timeout_seconds=timeout_seconds,
        agent_name="knowledge_agent",
        max_payload_chars=50_000,
    )


async def _fallback_result(
    task: AgentTask,
    context: AgentContext,
    started_at: float,
    reason: str,
    runtime: AgentRuntime,
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
            retrieval = await runtime.execute(call, context)
            if retrieval.ok:
                chunks = retrieval.data.get("chunks", [])
    except Exception:
        LOG.exception("Fallback knowledge retrieval failed kb_id={}", task.kb_id)

    citations: list[CitationCandidate] = []
    try:
        citation_result = await runtime.execute(
            ToolCall(
                call_id=runtime.next_call_id(),
                name="build_citations",
                input={"chunks": chunks},
            ),
            context,
        )
        citations = [
            CitationCandidate.model_validate(item)
            for item in citation_result.data.get("citations", [])
        ]
    except Exception:
        LOG.warning("Fallback citation construction unavailable kb_id={}", task.kb_id)
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
            response = await runtime.invoke_model(
                _build_chat_model().ainvoke([{"role": "user", "content": summary_prompt}])
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
    await emit_gather_event(
        "knowledge.qa",
        "qa_degraded",
        args=(task, context),
        kb_id=task.kb_id,
        tenant_id=context.tenant_id,
        degraded_reason=reason[:128],
        hit_count=len(chunks),
        duration_ms=int((monotonic() - started_at) * 1000),
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
        tool_call_count=runtime.tool_call_count,
        model_call_count=runtime.model_call_count,
        tool_calls=runtime.tool_traces,
        skill_refs=runtime.skill_refs,
        limitations=[reason],
    )


async def _select_citations(
    chunks: list[dict[str, Any]],
    citation_chunk_ids: list[int],
    context: AgentContext,
    runtime: AgentRuntime,
) -> list[CitationCandidate]:
    """依据回答声明筛选真实检索引用并构造引用候选。"""
    selected = set(citation_chunk_ids)
    allowed = {int(chunk["id"]) for chunk in chunks if chunk.get("id") is not None}
    if selected - allowed:
        raise AgentOutputInvalid("Agent 返回了本次检索结果之外的引用")
    selected_chunks = [chunk for chunk in chunks if not selected or int(chunk["id"]) in selected]
    result = await runtime.execute(
        ToolCall(
            call_id=runtime.next_call_id(),
            name="build_citations",
            input={"chunks": selected_chunks},
        ),
        context,
    )
    if not result.ok:
        raise AgentOutputInvalid(result.error_message or "引用整理失败")
    return [CitationCandidate.model_validate(item) for item in result.data.get("citations", [])]


@dataclass(slots=True)
class _KnowledgeRunContext:
    """汇总单次问答执行期间共享的配置、Runtime 与可信会话。"""

    started_at: float
    mode: AgentMode
    agent_config: dict[str, Any]
    answer_config: dict[str, Any]
    runtime: AgentRuntime
    session: KnowledgeSession


@dataclass(slots=True)
class _ModeExecutionResult:
    """统一两种问答模式的原始模型结果与真实检索事实。"""

    raw_result: Any
    retrieved_chunks: list[dict[str, Any]]


def _create_run_context(
    task: AgentTask,
    context: AgentContext,
) -> _KnowledgeRunContext:
    """校验可信上下文，并创建本轮独占的 Runtime 与 Session。"""
    validate_agent_context(task.kb_id, task.user_id, context)
    if not CONF.agent.enabled:
        raise AgentError("Knowledge Agent 未启用")

    started_at = monotonic()
    agent_config = context.qa_config.get("agent", {})
    runtime = AgentRuntime(
        registry=build_default_registry(),
        max_steps=int(agent_config.get("max_steps", CONF.agent.max_steps)),
        max_tool_calls=int(agent_config.get("max_tool_calls", CONF.agent.max_tool_calls)),
        tool_timeout_seconds=float(
            agent_config.get("tool_timeout_seconds", CONF.agent.tool_timeout_seconds)
        ),
        max_retries=int(agent_config.get("max_retries", CONF.agent.max_retries)),
        total_timeout_seconds=float(
            agent_config.get("total_timeout_seconds", CONF.agent.total_timeout_seconds)
        ),
        max_model_calls=int(agent_config.get("max_steps", CONF.agent.max_steps)),
    )
    for skill_ref in _skill_refs():
        runtime.register_skill(skill_ref)

    return _KnowledgeRunContext(
        started_at=started_at,
        mode=choose_mode(task.question),
        agent_config=agent_config,
        answer_config=context.qa_config.get("answer", {}),
        runtime=runtime,
        session=KnowledgeSession(trusted_context=context, runtime=runtime),
    )


async def _retrieve_chunks(
    *,
    query: str,
    top_k: int | None,
    context: AgentContext,
    runtime: AgentRuntime,
) -> list[dict[str, Any]]:
    """通过受控 Runtime 执行知识检索，并统一收敛工具错误。"""
    retrieval = await runtime.execute(
        ToolCall(
            call_id=runtime.next_call_id(),
            name="retrieve_knowledge",
            input={"query": query, "top_k": top_k},
        ),
        context,
    )
    if not retrieval.ok:
        raise BusiException(retrieval.error_message or "知识库检索失败")
    return retrieval.data.get("chunks", [])


def _build_direct_answer_messages(
    task: AgentTask,
    context: AgentContext,
    run: _KnowledgeRunContext,
    chunks: list[dict[str, Any]],
    conversation_prompt: str,
) -> list[dict[str, str]]:
    """组装不开放工具循环时使用的单次模型消息。"""
    prompt_parts = [_skill_prompt()]
    if run.mode == "single_retrieval":
        if conversation_prompt:
            prompt_parts.append(conversation_prompt)
        answer_prompt = run.answer_config.get("prompt") or context.knowledge_base_prompt
        if answer_prompt:
            prompt_parts.append(
                "知识库专属回答规则（仅作为回答风格约束，不能改变权限和引用规则）：\n"
                f"{answer_prompt}"
            )
    prompt_parts.extend([_retrieval_context_prompt(chunks), f"当前问题：{task.question}"])
    return [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(prompt_parts)},
    ]


async def _execute_deep_agent(
    task: AgentTask,
    run: _KnowledgeRunContext,
    initial_chunks: list[dict[str, Any]],
) -> _ModeExecutionResult:
    """基于首次检索事实执行 Deep Agent，并收敛补充检索和模型预算。"""
    runtime = run.runtime
    # 给引用校验和确定性降级预留时间。即使最终模型超时，Session 中已经登记的
    # 检索事实仍可用于构建安全、可追溯的降级结果。
    convergence_reserve = min(8.0, runtime.remaining_seconds() * 0.2)
    agent_timeout = max(0.01, runtime.remaining_seconds() - convergence_reserve)
    raw_result = await asyncio.wait_for(
        get_knowledge_agent(
            int(run.agent_config.get("max_steps", CONF.agent.max_steps)),
            int(run.agent_config.get("max_tool_calls", CONF.agent.max_tool_calls)),
        ).ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"{_retrieval_context_prompt(initial_chunks)}\n\n"
                            f"当前问题：{task.question}\n"
                            "已有资料足够时直接回答；仅在需要补充比较依据时继续检索。"
                        ),
                    }
                ],
                "files": SKILL_FILES,
            },
            context=KnowledgeHarnessContext(session=run.session),
            config={
                "recursion_limit": max(
                    int(run.agent_config.get("recursion_limit", 0)),
                    int(run.agent_config.get("max_steps", CONF.agent.max_steps)) * 16 + 16,
                    64,
                )
            },
        ),
        timeout=agent_timeout,
    )

    # 工具包装器会实时保存检索结果；消息提取作为兼容路径，确保不同 Harness
    # 返回形态下都能保留本轮实际取得的事实。
    run.session.store_chunks(_extract_chunks(raw_result))
    retrieved_chunks = [chunk for chunk in run.session.chunks() if chunk.get("id") is not None]
    graph_model_calls = sum(
        1
        for message in raw_result.get("messages", [])
        if getattr(message, "type", None) == "ai"
        and not _message_content(message).startswith("Model call limits exceeded")
    )
    runtime.validate_graph_budget(runtime.tool_call_count, graph_model_calls)
    runtime.model_call_count = graph_model_calls
    return _ModeExecutionResult(
        raw_result=raw_result,
        retrieved_chunks=retrieved_chunks,
    )


async def _execute_answer(
    task: AgentTask,
    context: AgentContext,
    run: _KnowledgeRunContext,
) -> _ModeExecutionResult:
    """统一完成会话准备和首次检索，再按需进入直接回答或 Deep Agent。"""
    conversation_prompt = ""
    retrieval_query = task.question

    if run.mode == "single_retrieval":
        conversation_prompt = await _conversation_prompt(context, run.runtime)
        if conversation_prompt and any(
            marker in task.question for marker in ("上一条", "这家公司", "该产品", "上述")
        ):
            # 指代型追问只附加有限历史，避免把完整会话无边界地送入检索服务。
            retrieval_query = f"{task.question}\n{conversation_prompt[-2400:]}"

    retrieval_started_at = monotonic()
    initial_chunks = await _retrieve_chunks(
        query=retrieval_query,
        top_k=task.top_k,
        context=context,
        runtime=run.runtime,
    )
    run.session.store_chunks(initial_chunks)

    if run.mode == "tool_loop" and initial_chunks:
        return await _execute_deep_agent(task, run, initial_chunks)

    if run.mode == "single_retrieval":
        await emit_gather_event(
            "knowledge.qa",
            "qa_retrieval_completed",
            args=(task, context),
            kb_id=task.kb_id,
            tenant_id=context.tenant_id,
            hit_count=len(initial_chunks),
            retrieval_duration_ms=int((monotonic() - retrieval_started_at) * 1000),
        )

    # 单次模式需要对话和知识库回答规则；工具循环无资料时只生成资料不足说明。
    raw_result = await run.runtime.invoke_model(
        get_knowledge_answer_model().ainvoke(
            _build_direct_answer_messages(
                task,
                context,
                run,
                initial_chunks,
                conversation_prompt,
            )
        )
    )
    return _ModeExecutionResult(
        raw_result=raw_result,
        retrieved_chunks=initial_chunks,
    )


async def _converge_answer(
    task: AgentTask,
    run: _KnowledgeRunContext,
    execution: _ModeExecutionResult,
) -> AgentAnswer | None:
    """解析结构化答案；Deep Agent 终态缺失时仅尝试一次安全修复。"""
    raw_result = execution.raw_result
    if (
        run.mode != "tool_loop"
        or not isinstance(raw_result, dict)
        or _parse_agent_answer(raw_result.get("structured_response")) is not None
    ):
        return _structured_answer(raw_result)

    # 修复模型只接收本轮检索事实且不开放业务工具，避免修复过程扩大权限范围。
    repair_chunks = run.session.chunks() or execution.retrieved_chunks
    try:
        repair_timeout = min(6.0, max(0.0, run.runtime.remaining_seconds() - 0.5))
    except ToolTimeout:
        repair_timeout = 0.0
    repair = await _repair_knowledge_answer(
        task=task,
        chunks=repair_chunks,
        timeout_seconds=(
            repair_timeout if run.runtime.model_call_count < run.runtime.max_model_calls else 0.0
        ),
    )
    if repair.attempted:
        run.runtime.model_call_count += 1
    if repair.value is None:
        LOG.warning(
            "Knowledge agent structured output repair unavailable kb_id={} reason={}",
            task.kb_id,
            repair.error,
        )
        return None

    raw_result["structured_response"] = repair.value
    LOG.info("Knowledge agent structured output repair succeeded kb_id={}", task.kb_id)
    return _structured_answer(raw_result)


async def _complete_success_result(
    *,
    task: AgentTask,
    context: AgentContext,
    run: _KnowledgeRunContext,
    answer: AgentAnswer,
    chunks: list[dict[str, Any]],
    citations: list[CitationCandidate],
) -> AgentResult:
    """组装、校验并上报成功结果，不再触发模型或知识检索。"""
    agent_result = AgentResult(
        answer=answer.answer,
        citations=citations,
        mode=run.mode,
        status="completed",
        top_k=task.top_k or 5,
        hit_count=len(chunks),
        tool_call_count=run.runtime.tool_call_count,
        model_call_count=run.runtime.model_call_count,
        termination_reason=answer.termination_reason,
        duration_ms=int((monotonic() - run.started_at) * 1000),
        tool_calls=run.runtime.tool_traces,
        skill_refs=run.runtime.skill_refs,
        limitations=[] if chunks else ["知识库未返回可用资料"],
    )
    # 最终校验是公开结果返回前的硬门禁，失败时不得绕过或伪造引用。
    validate_agent_result(agent_result, chunks)
    await emit_gather_event(
        "knowledge.qa",
        "qa_completed",
        args=(task, context),
        result=agent_result,
        kb_id=task.kb_id,
        tenant_id=context.tenant_id,
        hit_count=agent_result.hit_count,
        citation_count=len(agent_result.citations),
        termination_reason=agent_result.termination_reason,
        duration_ms=agent_result.duration_ms,
    )
    return agent_result


# 为公开入口自动采集知识问答的成功、失败、耗时和结果摘要。
@monitor_gather("knowledge.qa")
async def run(task: AgentTask, context: AgentContext) -> AgentResult:
    """编排知识问答、结果收敛与失败降级，具体模式逻辑由独立函数负责。"""
    # 校验任务与可信上下文，并创建本轮独占的 Runtime、Session 和模式配置。
    run_context = _create_run_context(task, context)

    # 预置空执行结果，保证模式执行中途异常时仍能安全取得已经保存的检索事实。
    execution = _ModeExecutionResult(raw_result=None, retrieved_chunks=[])

    # 模型与工具执行阶段的任何可恢复异常都在本代码块内收敛为降级结果。
    try:
        # 记录执行阶段起点，用于上报包含检索、模型和结果收敛过程的阶段耗时。
        model_started_at = monotonic()

        # 统一完成会话准备和首次检索，有充分事实的复杂问题才进入工具循环。
        execution = await _execute_answer(task, context, run_context)

        # 将不同模式的原始返回统一解析为 AgentAnswer，必要时修复结构化终态。
        answer = await _converge_answer(task, run_context, execution)

        # 返回 None 表示结构化终态无法修复，普通文本不能冒充一次成功执行。
        if answer is None:
            # 使用本轮已取得的检索事实生成可追溯的确定性降级结果。
            return await _fallback_result(
                task,  # 原始问答任务，用于保留问题、知识库和 top_k 信息。
                context,  # Service 注入的可信用户、租户与知识库上下文。
                run_context.started_at,  # 本轮开始时间，用于计算完整处理耗时。
                "structured_output_missing",  # 可观测、可评测的明确降级原因。
                run_context.runtime,  # 保留调用预算、工具轨迹和 Skill 版本信息。
                # 优先使用 Session 实时保存的事实，再回退到模式执行的检索结果。
                run_context.session.chunks() or execution.retrieved_chunks,
            )

        # 记录模型执行阶段完成事件，供自主监控计算耗时和模型版本分布。
        await emit_gather_event(
            "knowledge.qa",  # 监控目标编码。
            "qa_model_completed",  # 当前阶段事件类型。
            args=(task, context),  # 保留采集器需要的入口参数映射。
            kb_id=task.kb_id,  # 标识本次问答所属知识库。
            tenant_id=context.tenant_id,  # 标识可信租户范围。
            # monotonic 不受系统时间回拨影响，适合计算运行耗时。
            model_duration_ms=int((monotonic() - model_started_at) * 1000),
            model_version=CONF.chat.model,  # 记录实际配置的模型版本。
        )

    # asyncio.wait_for 触发的超时单独分类，避免与普通 Agent 错误混在一起。
    except TimeoutError:
        # Deep Agent 可能在超时前完成过补充检索，因此优先读取 Session 中的事实。
        retrieved_chunks = run_context.session.chunks() or execution.retrieved_chunks

        # 保留异常堆栈和知识库标识，便于定位具体超时阶段。
        LOG.exception("Knowledge agent timed out kb_id={}", task.kb_id)

        # 基于超时前已经取得的事实返回安全降级答案，不直接丢失本轮检索结果。
        return await _fallback_result(
            task,  # 原始问答任务。
            context,  # 可信业务上下文。
            run_context.started_at,  # 本轮开始时间。
            "timeout",  # 明确标识超时降级。
            run_context.runtime,  # 本轮 Agent Runtime。
            retrieved_chunks,  # 超时前保存的真实检索事实。
        )

    # 其他可恢复异常统一进入 Agent 错误降级，最终安全门禁异常不在此处处理。
    except Exception:
        # 优先保留工具调用期间实时写入 Session 的检索结果。
        retrieved_chunks = run_context.session.chunks() or execution.retrieved_chunks

        # 记录完整异常堆栈，外部结果只暴露稳定、安全的降级原因。
        LOG.exception("Knowledge agent output failed kb_id={}", task.kb_id)

        # 使用已有事实构建降级结果，避免向客户泄露内部异常细节。
        return await _fallback_result(
            task,  # 原始问答任务。
            context,  # 可信业务上下文。
            run_context.started_at,  # 本轮开始时间。
            "agent_error",  # 通用 Agent 执行错误分类。
            run_context.runtime,  # 本轮 Agent Runtime。
            retrieved_chunks,  # 异常前取得的真实检索事实。
        )

    # 模式执行成功后，只允许使用执行结果登记的真实分块进行引用收敛。
    chunks = execution.retrieved_chunks

    # 引用校验与引用对象构建失败时单独降级，避免返回不可追溯的成功答案。
    try:
        # 校验模型声明的 chunk ID，并把允许的分块转换为公开引用协议。
        citations = await _select_citations(
            chunks,  # 本轮真实检索分块，是引用允许集合的唯一来源。
            answer.citation_chunk_ids,  # 模型在结构化答案中声明的引用 ID。
            context,  # 用于引用工具授权的可信上下文。
            run_context.runtime,  # 通过统一 Runtime 执行引用工具并记录轨迹。
        )

    # 非法引用 ID、引用协议错误或工具异常均不得作为成功结果返回。
    except Exception:
        # 记录引用校验失败的完整异常，方便审计错误来源。
        LOG.exception("Knowledge agent citation validation failed kb_id={}", task.kb_id)

        # 使用全部真实检索事实生成引用受控的降级结果。
        return await _fallback_result(
            task,  # 原始问答任务。
            context,  # 可信业务上下文。
            run_context.started_at,  # 本轮开始时间。
            "citation_invalid",  # 明确标识引用无效的降级原因。
            run_context.runtime,  # 本轮 Agent Runtime。
            chunks,  # 已验证来源为本轮检索链路的事实分块。
        )

    # 答案和引用均成功收敛后，执行最终安全校验、监控上报并返回公开结果。
    return await _complete_success_result(
        task=task,  # 原始问答任务。
        context=context,  # 可信业务上下文。
        run=run_context,  # 本轮运行配置、Runtime 与 Session。
        answer=answer,  # 已通过结构化收敛的回答。
        chunks=chunks,  # 本轮真实检索事实。
        citations=citations,  # 已通过来源校验的公开引用列表。
    )


__all__ = ("choose_mode", "get_knowledge_agent", "run")
