from __future__ import annotations

from app.core.common.exception import BusiException
from app.schemas.evaluation import EvaluationAgentContext

from .models import EvaluationConfig


def validate_config(config: EvaluationConfig) -> None:
    if config.user_id is None:
        raise BusiException("CONFIG_INVALID: 评测执行用户尚未解析")
    if config.business_scope_source == "description" and not config.business_description:
        raise BusiException("CONFIG_INVALID: description 模式必须提供业务描述")
    if (
        config.business_scope_source == "description_and_knowledge_base"
        and not config.business_description
    ):
        raise BusiException("CONFIG_INVALID: 组合模式必须提供业务描述")
    if config.questions_source == "imported" and not config.questions_file:
        raise BusiException("CONFIG_INVALID: imported 模式必须提供问题文件")


def authorize_evaluation(*, is_super_admin: bool) -> None:
    if not is_super_admin:
        raise BusiException("无权操作自主评测", status_code=403)


def validate_evaluation_context(
    config: EvaluationConfig,
    context: EvaluationAgentContext,
) -> None:
    authorize_evaluation(is_super_admin=context.is_super_admin)
    if config.kb_id != context.kb_id or str(config.user_id) != context.user_id:
        raise BusiException("评测任务与可信执行上下文不一致", status_code=403)


def authorize_evaluation_tool(
    *,
    name: str,
    payload: dict,
    context: EvaluationAgentContext,
    registered_tools: frozenset[str],
) -> None:
    validate_context_fields = {
        "tenant_id",
        "organization_ids",
        "user_id",
        "kb_id",
        "index_version_id",
    }
    if name != "call_knowledge_agent" or name not in registered_tools:
        raise BusiException("评测工具未授权", status_code=403)
    overridden = validate_context_fields.intersection(payload)
    if overridden:
        raise BusiException(
            f"评测工具输入不允许覆盖可信字段: {sorted(overridden)[0]}",
            status_code=403,
        )
    if context.kb_id <= 0 or not context.user_id:
        raise BusiException("评测工具可信上下文无效", status_code=403)
