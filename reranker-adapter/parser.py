"""Parse Ollama generation responses into reranker scores."""

import math
from typing import Any


class ModelResultError(ValueError):
    """Raised when Ollama returns an unusable reranker result."""


def parse_score(payload: dict[str, Any], *, fallback_binary_score: bool) -> tuple[float, str]:
    response = str(payload.get("response", "")).strip().lower()
    probabilities: dict[str, float] = {}
    for item in payload.get("logprobs") or []:
        for candidate in item.get("top_logprobs") or []:
            token = str(candidate.get("token", "")).strip().lower()
            logprob = candidate.get("logprob")
            if token in {"yes", "no"} and isinstance(logprob, (int, float)):
                probabilities[token] = float(logprob)

    if "yes" in probabilities and "no" in probabilities:
        yes_exp = math.exp(probabilities["yes"])
        no_exp = math.exp(probabilities["no"])
        denominator = yes_exp + no_exp
        if denominator > 0:
            return yes_exp / denominator, "logprob"

    if fallback_binary_score and response in {"yes", "no"}:
        return (1.0 if response == "yes" else 0.0), "binary_fallback"

    raise ModelResultError("模型未返回可解析的 yes/no 判断或对应概率")
