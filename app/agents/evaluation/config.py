"""自主评测配置的文件加载、覆盖合并与安全快照。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.common.exception import BusiException

from .models import EvaluationConfig, Gate

SENSITIVE_KEYS = ("password", "token", "api_key", "secret", "authorization")


def _redact(value: Any) -> Any:
    """递归遮蔽配置中的密钥、令牌和密码字段。"""
    if isinstance(value, dict):
        return {
            key: ("***" if any(item in key.lower() for item in SENSITIVE_KEYS) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def load_config(
    path: str | Path | None = None, overrides: dict[str, Any] | None = None
) -> EvaluationConfig:
    """合并配置文件和显式覆盖项，并校验为评测配置模型。"""
    raw: dict[str, Any] = {}
    if path is not None:
        try:
            loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise BusiException("CONFIG_INVALID: 评测配置文件无法读取") from exc
        raw = loaded.get("evaluation", loaded)
    raw = {**raw, **(overrides or {})}
    questions = raw.pop("questions", {}) or {}
    business_scope = raw.pop("business_scope", {}) or {}
    execution = raw.pop("execution", {}) or {}
    raw = {
        **raw,
        "questions_source": raw.get("questions_source", questions.get("source", "imported")),
        "questions_count": raw.get("questions_count", questions.get("count", 20)),
        "questions_file": raw.get("questions_file", questions.get("file")),
        "questions_instruction": raw.get("questions_instruction", questions.get("instruction")),
        "business_scope_source": raw.get(
            "business_scope_source", business_scope.get("source", "description")
        ),
        "business_description": raw.get("business_description", business_scope.get("description")),
        "user_id": raw.get("user_id", execution.get("user_id")),
        "concurrency": raw.get("concurrency", execution.get("concurrency", 3)),
        "request_timeout_seconds": raw.get(
            "request_timeout_seconds", execution.get("request_timeout_seconds", 120)
        ),
        "retry_count": raw.get("retry_count", execution.get("retry_count", 0)),
        "max_review_rounds": raw.get("max_review_rounds", execution.get("max_review_rounds", 1)),
        "max_model_calls": raw.get("max_model_calls", execution.get("max_model_calls", 5)),
        "keep_conversation": raw.get(
            "keep_conversation", execution.get("keep_conversation", False)
        ),
    }
    try:
        gates = {name: Gate.model_validate(value) for name, value in raw.get("gates", {}).items()}
        config = EvaluationConfig.model_validate({**raw, "gates": gates})
    except ValueError as exc:
        raise BusiException(
            "CONFIG_INVALID: 评测配置校验失败", payload={"errors": str(exc)}
        ) from exc
    return config


def config_snapshot(config: EvaluationConfig) -> dict[str, Any]:
    """生成可用于日志和报告的脱敏配置快照。"""
    return _redact(config.model_dump(mode="json"))
