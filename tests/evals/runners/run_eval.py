from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from tests.evals.metrics.generation import (
    abstention_correct,
    answer_correctness,
    answer_relevancy,
    citation_accuracy,
    faithfulness,
    generation_summary,
)
from tests.evals.metrics.retrieval import (
    context_recall,
    is_relevant,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
)


def _request(
    base_url: str,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str = "",
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return {"status": response.status, "body": json.load(response)}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except json.JSONDecodeError:
            body = {"detail": "HTTP request failed"}
        return {"status": exc.code, "body": body}


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip() and not line.startswith("#")]


def _login(base_url: str, account: str, password: str) -> str:
    response = _request(
        base_url,
        "/auth/login",
        method="POST",
        body={"account": account, "password": password},
    )
    if response["status"] != 200:
        raise RuntimeError(f"login failed: {response['body']}")
    return str(response["body"]["access_token"])


def _retrieve(base_url: str, case: dict[str, Any], token: str) -> dict[str, Any]:
    return _request(
        base_url,
        "/search",
        method="POST",
        body={
            "kb_id": case["kb_id"],
            "query": case["question"],
            "top_k": case.get("top_k", 5),
        },
        token=token,
    )


def _chat(
    base_url: str,
    case: dict[str, Any],
    token: str,
    conversation_id: int | None,
) -> dict[str, Any]:
    endpoint = "/guest/chat" if case.get("guest", True) else "/chat"
    body = {
        "kb_id": case["kb_id"],
        "question": case["question"],
        "top_k": case.get("top_k", 5),
    }
    if conversation_id:
        body["conversation_id"] = conversation_id
    if not case.get("guest", True):
        body["user_id"] = case.get("user_id", "eval-user")
    return _request(base_url, endpoint, method="POST", body=body, token=token)


def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(Path(args.dataset))
    token = args.token or _login(args.base_url, args.account, args.password)
    retrieval_rows: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    conversation_ids: dict[str, int] = {}

    for case in cases:
        started = time.perf_counter()
        retrieval_response = _retrieve(args.base_url, case, token)
        retrieval_body = retrieval_response.get("body", {})
        chunks = retrieval_body.get("chunks", []) if retrieval_response["status"] == 200 else []
        retrieval_row = {
            "case_id": case["case_id"],
            "status": retrieval_response["status"],
            "chunks": chunks,
            "reciprocal_rank": reciprocal_rank(chunks, case),
            "precision_at_5": precision_at_k(chunks, case, 5),
            "ndcg_at_5": ndcg_at_k(chunks, case, 5),
            "context_recall": context_recall(
                "\n".join(str(chunk.get("content", "")) for chunk in chunks),
                case,
            ),
        }
        retrieval_rows.append(retrieval_row)

        conversation_group = str(case.get("conversation_group") or case["case_id"])
        chat_response = _chat(
            args.base_url,
            case,
            token,
            conversation_ids.get(conversation_group),
        )
        chat_body = chat_response.get("body", {})
        if chat_response["status"] == 200:
            returned_conversation_id = chat_body.get("conversation_id")
            if returned_conversation_id:
                conversation_ids[conversation_group] = returned_conversation_id
        answer = str(chat_body.get("answer", ""))
        citations = chat_body.get("citations", [])
        context = "\n".join(str(chunk.get("content", "")) for chunk in chunks)
        generation_rows.append(
            {
                "case_id": case["case_id"],
                "status": chat_response["status"],
                "answer": answer,
                "citations": citations,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "faithfulness": faithfulness(answer, context),
                "answer_relevancy": answer_relevancy(answer, case),
                "answer_correctness": answer_correctness(answer, case),
                "citation_accuracy": citation_accuracy(chat_body, case),
                "abstention_accuracy": abstention_correct(answer, case),
                "fallback": (
                    "fallback" in str(chat_body.get("termination_reason", ""))
                    or answer.startswith("当前智能问答暂时无法")
                ),
            }
        )

    return {
        "dataset": str(args.dataset),
        "case_count": len(cases),
        "rerank": {
            "enabled": os.getenv("KB_RAG_RERANK_ENABLED", "true").lower() == "true",
            "model": os.getenv(
                "KB_RAG_RERANK_MODEL",
                "hans-tech/bge-reranker-v2-m3:260522",
            ),
            "base_url": os.getenv(
                "KB_RAG_RERANK_BASE_URL",
                "http://127.0.0.1:11434",
            ),
            "endpoint": os.getenv("KB_RAG_RERANK_ENDPOINT", "/api/rerank"),
        },
        "retrieval": {
            "recall_at_1": sum(
                any(is_relevant(chunk, case) for chunk in row["chunks"][:1])
                for row, case in zip(retrieval_rows, cases, strict=True)
            )
            / len(cases),
            "recall_at_5": sum(
                any(is_relevant(chunk, case) for chunk in row["chunks"][:5])
                for row, case in zip(retrieval_rows, cases, strict=True)
            )
            / len(cases),
            "mrr": mean_reciprocal_rank(retrieval_rows),
            "precision_at_5": sum(row["precision_at_5"] for row in retrieval_rows)
            / len(retrieval_rows),
            "ndcg_at_5": sum(row["ndcg_at_5"] for row in retrieval_rows)
            / len(retrieval_rows),
            "context_recall": sum(row["context_recall"] for row in retrieval_rows)
            / len(retrieval_rows),
        },
        "generation": generation_summary(generation_rows),
        "performance": {
            "p50_duration_ms": _percentile([row["duration_ms"] for row in generation_rows], 0.50),
            "p95_duration_ms": _percentile([row["duration_ms"] for row in generation_rows], 0.95),
            "error_rate": sum(row["status"] >= 400 for row in generation_rows)
            / len(generation_rows),
            "fallback_rate": sum(row["fallback"] for row in generation_rows) / len(generation_rows),
        },
        "retrieval_rows": retrieval_rows,
        "generation_rows": generation_rows,
    }


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    index = min(len(values) - 1, max(0, round((len(values) - 1) * ratio)))
    return values[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run knowledge-base retrieval and chat evaluation")
    parser.add_argument("--dataset", required=True, help="JSONL evaluation dataset")
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:28003/api/v1"))
    parser.add_argument("--account", default=os.getenv("EVAL_ACCOUNT", "guest"))
    parser.add_argument("--password", default=os.getenv("EVAL_PASSWORD", "guest"))
    parser.add_argument("--token", default=os.getenv("EVAL_TOKEN", ""))
    parser.add_argument("--output", required=True, help="JSON report path")
    args = parser.parse_args()
    report = run(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("case_count", "retrieval", "generation", "performance")
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
