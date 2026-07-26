"""Execute one real autonomous-evaluation run and verify its persisted report."""

from __future__ import annotations

import asyncio
import os
import time

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


async def run_worker(run_id: int) -> None:
    from app.config import configure
    from app.db import setup
    from app.db import base
    from workers.evaluation import run_evaluation

    configure("app")
    await setup()
    await base.inject_db()
    try:
        await run_evaluation(run_id)
    finally:
        await base.DATABASE.disconnect()


def main() -> int:
    token = login(os.getenv("TEST_ADMIN_ACCOUNT"), os.getenv("TEST_ADMIN_PASSWORD"))
    kb_id = int(os.getenv("TEST_EVAL_KB_ID", "34"))
    suffix = str(int(time.time()))
    task = expect(
        "create evaluation worker task",
        request(
            "POST",
            "/platform/evaluations",
            token=token,
            body={
                "name": f"自动化 Worker 测试-{suffix}",
                "kb_id": kb_id,
                "questions_source": "imported",
                "questions_file": "worker-smoke.jsonl",
                "questions_content": '{"question":"报销流程需要哪些材料？"}\n',
                "business_scope_source": "knowledge_base",
                "execution": {
                    "concurrency": 1,
                    "request_timeout_seconds": 30,
                    "retry_count": 0,
                    "keep_conversation": False,
                },
            },
        ),
        {200, 201},
    ).body
    task_id = int(task["id"])
    try:
        run = expect(
            "create evaluation worker run",
            request("POST", f"/platform/evaluations/{task_id}/runs", token=token, body={}),
            {200, 201},
        ).body
        run_id = int(run["id"])
        asyncio.run(run_worker(run_id))
        detail = expect(
            "evaluation worker run detail",
            request("GET", f"/platform/evaluations/{task_id}/runs/{run_id}", token=token),
            {200},
        ).body
        if detail.get("status") != "completed":
            raise AssertionError(f"worker run did not complete: {detail}")
        if int(detail.get("question_count") or 0) != 1:
            raise AssertionError(f"worker result count mismatch: {detail}")
        cases = expect(
            "evaluation worker case results",
            request("GET", f"/platform/evaluations/{task_id}/runs/{run_id}/cases", token=token),
            {200},
        ).body
        if int(cases.get("total") or 0) != 1:
            raise AssertionError(f"worker case count mismatch: {cases}")
    finally:
        expect("delete evaluation worker task", request("DELETE", f"/platform/evaluations/{task_id}", token=token), {200})
    print("autonomous evaluation worker documented cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
