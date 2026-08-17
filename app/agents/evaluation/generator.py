"""自主评测问题生成器的受控扩展协议。"""

from __future__ import annotations

from app.core.common.log import LOG

from .models import EvaluationConfig, EvaluationQuestion


async def generate_questions(
    config: EvaluationConfig, knowledge_text: str | None = None
) -> list[EvaluationQuestion]:
    """生成器协议占位：实际生成必须由受控的上层模型适配器注入。"""
    LOG.info(
        "自主评测Agent question generation start kb_id={} count={} scope_source={}",
        config.kb_id,
        config.questions_count,
        config.business_scope_source,
    )
    basis = (
        "both"
        if config.business_scope_source == "description_and_knowledge_base"
        else config.business_scope_source
    )
    if config.business_scope_source == "description" and not config.business_description:
        raise ValueError("business description is required")
    if (
        config.business_scope_source in {"knowledge_base", "description_and_knowledge_base"}
        and not knowledge_text
    ):
        raise ValueError("knowledge text is required")
    questions = [
        EvaluationQuestion(
            question=(
                f"请说明以下业务范围中的第 {index} 个关键问题："
                f"{config.business_description or knowledge_text}"
            ),
            source="generated",
            question_basis=basis,
        )
        for index in range(1, config.questions_count + 1)
    ]
    LOG.info(
        "自主评测Agent question generation completed kb_id={} result_count={}",
        config.kb_id,
        len(questions),
    )
    return questions
