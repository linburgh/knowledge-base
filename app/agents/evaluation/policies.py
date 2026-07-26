from __future__ import annotations

from app.core.common.exception import BusiException

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
