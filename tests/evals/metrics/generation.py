from __future__ import annotations

import re
from typing import Any

from .retrieval import average, tokens


def answer_relevancy(answer: str, case: dict[str, Any]) -> float:
    reference = str(case.get("expected_answer") or case.get("question") or "")
    expected = tokens(reference)
    actual = tokens(answer)
    if not expected:
        return 1.0 if actual else 0.0
    return len(expected & actual) / len(expected)


def faithfulness(answer: str, context: str) -> float:
    sentences = [item.strip() for item in re.split(r"[。！？.!?\n]+", answer) if item.strip()]
    if not sentences:
        return 0.0
    context_tokens = tokens(context)
    supported = sum(bool(tokens(sentence) & context_tokens) for sentence in sentences)
    return supported / len(sentences)


def answer_correctness(answer: str, case: dict[str, Any]) -> float:
    expected = tokens(str(case.get("expected_answer") or ""))
    actual = tokens(answer)
    if not expected:
        return 0.0
    return len(expected & actual) / len(expected)


def citation_accuracy(response: dict[str, Any], case: dict[str, Any]) -> float:
    citations = response.get("citations") or []
    if not citations:
        return 0.0 if case.get("answerable", True) else 1.0
    expected_sources = set(case.get("expected_document_names", []))
    if not expected_sources:
        return 1.0
    matched = sum(str(item.get("source_name", "")) in expected_sources for item in citations)
    return matched / len(citations)


def abstention_correct(answer: str, case: dict[str, Any]) -> float:
    if case.get("answerable", True):
        return 1.0 if answer.strip() else 0.0
    markers = ("没有", "不足", "无法确认", "未提及", "不确定", "不包含", "请提供")
    return 1.0 if any(marker in answer for marker in markers) else 0.0


def generation_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "faithfulness": average(row.get("faithfulness", 0) for row in rows),
        "answer_relevancy": average(row.get("answer_relevancy", 0) for row in rows),
        "answer_correctness": average(row.get("answer_correctness", 0) for row in rows),
        "citation_accuracy": average(row.get("citation_accuracy", 0) for row in rows),
        "abstention_accuracy": average(row.get("abstention_accuracy", 0) for row in rows),
    }
