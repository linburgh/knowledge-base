"""Exercise the documented knowledge-base QA configuration flow on a test KB."""

from __future__ import annotations

import os

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


def main() -> int:
    token = login(os.getenv("TEST_ADMIN_ACCOUNT"), os.getenv("TEST_ADMIN_PASSWORD"))
    kb_id = int(os.getenv("TEST_QA_KB_ID", "34"))
    config = expect("QA config get", request("GET", f"/knowledge-bases/{kb_id}/qa-config", token=token), {200}).body
    draft_record = config.get("draft") or {}
    published_record = config.get("published") or {}
    version = draft_record.get("version") or published_record.get("version")
    effective = (
        draft_record.get("config")
        or published_record.get("config")
        or config.get("effective")
        or {}
    )

    expect(
        "QA prompt preview",
        request(
            "POST",
            f"/knowledge-bases/{kb_id}/qa-config/prompt-preview",
            token=token,
            body={"question": "测试文档中记录了什么？", "config": effective},
        ),
        {200},
    )
    expect(
        "QA retrieval test",
        request(
            "POST",
            f"/knowledge-bases/{kb_id}/qa-config/retrieval-test",
            token=token,
            body={"question": "测试文档中记录了什么？", "config": effective},
        ),
        {200},
    )
    expect(
        "QA rerank test",
        request(
            "POST",
            f"/knowledge-bases/{kb_id}/qa-config/rerank-test",
            token=token,
            body={"question": "测试文档中记录了什么？", "config": effective},
        ),
        {200},
    )
    expect(
        "QA invalid retrieval config rejected",
        request(
            "POST",
            f"/knowledge-bases/{kb_id}/qa-config/retrieval-test",
            token=token,
            body={"question": "测试", "config": {"retrieval": {"top_k": 21}}},
        ),
        {400, 422},
    )

    draft = dict(effective)
    retrieval = dict(draft.get("retrieval") or {})
    retrieval["top_k"] = int(retrieval.get("top_k") or 5)
    draft["retrieval"] = retrieval
    draft_body = {"config": draft}
    if version is not None:
        draft_body["base_version"] = int(version)
    saved = expect(
        "QA draft save",
        request(
            "PUT",
            f"/knowledge-bases/{kb_id}/qa-config/draft",
            token=token,
            body=draft_body,
        ),
        {200},
    ).body
    saved_config = expect(
        "QA draft readback",
        request("GET", f"/knowledge-bases/{kb_id}/qa-config", token=token),
        {200},
    ).body
    saved_version = int((saved_config.get("draft") or {}).get("version_no") or version or 1)
    if version is not None:
        expect(
            "QA stale draft conflict",
            request(
                "PUT",
                f"/knowledge-bases/{kb_id}/qa-config/draft",
                token=token,
                body={"config": draft, "base_version": int(version) - 1},
            ),
            {409},
        )
    expect(
        "QA publish draft",
        request(
            "POST",
            f"/knowledge-bases/{kb_id}/qa-config/publish",
            token=token,
            body={"base_version": saved_version},
        ),
        {200},
    )
    expect("QA reset default", request("POST", f"/knowledge-bases/{kb_id}/qa-config/reset", token=token), {200})
    print("documented QA configuration cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
