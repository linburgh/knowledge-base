from __future__ import annotations

from .models import EvaluationConfig, EvaluationQuestion


async def generate_questions(
    config: EvaluationConfig, knowledge_text: str | None = None
) -> list[EvaluationQuestion]:
    """生成器协议占位：实际生成必须由受控的上层模型适配器注入。"""
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
    return [
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
