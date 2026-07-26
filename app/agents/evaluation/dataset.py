from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.common.exception import BusiException

from .models import EvaluationQuestion


def load_questions(path: str | Path) -> list[EvaluationQuestion]:
    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BusiException("DATASET_INVALID: 问题文件无法读取") from exc
    if not content.strip():
        raise BusiException("DATASET_INVALID: 问题文件为空")
    return load_questions_content(content, file_path.suffix)


def load_questions_content(content: str, suffix: str) -> list[EvaluationQuestion]:
    try:
        normalized_suffix = Path(suffix).suffix.lower() or suffix.lower()
        if normalized_suffix == ".txt":
            rows: list[Any] = [{"question": line} for line in content.splitlines() if line.strip()]
        elif normalized_suffix == ".jsonl":
            rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        elif normalized_suffix == ".json":
            loaded = json.loads(content)
            rows = loaded if isinstance(loaded, list) else [loaded]
        else:
            raise ValueError("unsupported extension")
        questions = [EvaluationQuestion.model_validate(row) for row in rows]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise BusiException("DATASET_INVALID: 问题文件格式或字段不合法") from exc
    if not questions:
        raise BusiException("DATASET_INVALID: 没有有效问题")
    seen_questions: set[str] = set()
    seen_case_ids: set[str] = set()
    unique: list[EvaluationQuestion] = []
    for question in questions:
        if question.question in seen_questions or (
            question.case_id and question.case_id in seen_case_ids
        ):
            continue
        seen_questions.add(question.question)
        if question.case_id:
            seen_case_ids.add(question.case_id)
        unique.append(question)
    return unique
