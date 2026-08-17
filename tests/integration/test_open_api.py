"""Exercise the developer Open API facade against the running backend."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:28003/api/v1")


def request(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def login(account: str, password: str) -> str:
    status, body = request("POST", "/auth/login", body={"account": account, "password": password})
    assert status == 200, body
    return body["access_token"]


def check(name: str, status: int, body: dict, expected: int) -> None:
    assert status == expected, (name, status, body)
    print(f"PASS {name}: HTTP {status}")


def main() -> int:
    admin = login(os.environ["TEST_ADMIN_ACCOUNT"], os.environ["TEST_ADMIN_PASSWORD"])
    guest = login(os.environ["TEST_GUEST_ACCOUNT"], os.environ["TEST_GUEST_PASSWORD"])

    status, body = request("GET", "/open/knowledge-bases", admin)
    check("open knowledge-base list", status, body, 200)
    assert {"items", "total", "page", "page_size"} <= body.keys()

    status, body = request("GET", "/open/knowledge-bases", guest)
    check("open guest knowledge-base list", status, body, 200)

    status, body = request("GET", "/open/knowledge-bases")
    check("open missing token", status, body, 401)
    assert body["code"] == "UNAUTHORIZED" and body["request_id"]

    status, body = request("POST", "/open/search", admin, {"knowledge_base_id": 34})
    check("open validation", status, body, 422)
    assert body["code"] == "VALIDATION_ERROR" and body["request_id"]

    status, body = request(
        "POST",
        "/open/search",
        guest,
        {"knowledge_base_id": 999999, "query": "越权资源", "mode": "keyword", "top_k": 1},
    )
    check("open unauthorized knowledge-base", status, body, 403)
    assert body["code"] == "RESOURCE_FORBIDDEN"

    status, body = request("GET", "/open/documents/999999", admin)
    check("open missing document", status, body, 404)
    assert body["code"] == "RESOURCE_NOT_FOUND"

    status, body = request("GET", "/open/conversations/999999/messages", admin)
    check("open conversation ownership boundary", status, body, 404)

    rate_limited = False
    for _ in range(70):
        status, body = request("GET", "/open/knowledge-bases", admin)
        if status == 429:
            rate_limited = True
            assert body["code"] == "RATE_LIMITED" and body["request_id"]
            break
    assert rate_limited, "open API did not return 429 after the configured request limit"
    print("PASS open API rate limiting: HTTP 429")
    print("Open API authentication, permissions, validation, ownership and rate-limit cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
