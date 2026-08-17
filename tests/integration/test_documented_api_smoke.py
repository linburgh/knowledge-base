"""Run the executable API smoke cases referenced by docs/测试用例.

This runner intentionally uses runtime credentials and IDs.  It does not seed or
delete business data, so it can be rerun against an existing test environment.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:28003/api/v1").rstrip("/")
ADMIN_ACCOUNT = os.getenv("TEST_ADMIN_ACCOUNT")
ADMIN_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD")
GUEST_ACCOUNT = os.getenv("TEST_GUEST_ACCOUNT")
GUEST_PASSWORD = os.getenv("TEST_GUEST_PASSWORD")
TENANT_ID = int(os.getenv("TEST_TENANT_ID", "3"))


@dataclass
class Response:
    status: int
    body: Any


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request_obj = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            return Response(response.status, json.loads(response.read().decode() or "null"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return Response(exc.code, parsed)


def login(account: str | None, password: str | None) -> str:
    if not account or not password:
        raise RuntimeError("TEST_ADMIN_ACCOUNT/TEST_ADMIN_PASSWORD or guest credentials are required")
    response = request("POST", "/auth/login", body={"account": account, "password": password})
    if response.status != 200:
        raise AssertionError(f"login failed: status={response.status}, body={response.body}")
    return str(response.body["access_token"])


def expect(name: str, response: Response, statuses: set[int]) -> Response:
    if response.status not in statuses:
        raise AssertionError(
            f"{name} failed: expected={sorted(statuses)}, status={response.status}, body={response.body}"
        )
    print(f"PASS {name}: HTTP {response.status}")
    return response


def main() -> int:
    admin_token = login(ADMIN_ACCOUNT, ADMIN_PASSWORD)

    expect("health without auth", request("GET", "/health"), {200})
    overview = expect(
        "platform overview",
        request("GET", "/platform/overview", token=admin_token),
        {200},
    ).body
    non_business_actions = {"login", "logout", "refresh_token", "select_tenant"}
    assert not any(
        item["action"] in non_business_actions
        for item in overview["recent_activities"]
    )
    expect("user page", request("GET", "/users/page?page=1&page_size=5", token=admin_token), {200})
    expect("tenant page", request("GET", "/tenants/page?page=1&page_size=5", token=admin_token), {200})
    expect(
        "organization page",
        request("GET", f"/organizations/page?tenant_id={TENANT_ID}&page=1&page_size=5", token=admin_token),
        {200},
    )
    knowledge_bases = expect(
        "knowledge-base page",
        request("GET", "/knowledge-bases/page?page=1&page_size=5", token=admin_token),
        {200},
    )
    expect("evaluation page", request("GET", "/platform/evaluations/page?page=1&page_size=5", token=admin_token), {200})

    rows = knowledge_bases.body.get("rows") or knowledge_bases.body.get("items") or []
    if rows:
        kb_id = int(rows[0]["id"])
        expect("knowledge-base overview", request("GET", f"/knowledge-bases/{kb_id}/overview", token=admin_token), {200})
        expect("document page", request("GET", f"/documents?kb_id={kb_id}", token=admin_token), {200})
        expect("QA config query", request("GET", f"/knowledge-bases/{kb_id}/qa-config", token=admin_token), {200})

    for name, path in [
        ("unauthenticated platform overview", "/platform/overview"),
        ("unauthenticated user page", "/users/page?page=1&page_size=5"),
        ("unauthenticated tenant page", "/tenants/page?page=1&page_size=5"),
        ("unauthenticated organization page", f"/organizations/page?tenant_id={TENANT_ID}"),
        ("unauthenticated knowledge-base page", "/knowledge-bases/page?page=1&page_size=5"),
        ("unauthenticated evaluation page", "/platform/evaluations/page?page=1&page_size=5"),
        ("unauthenticated conversation list", "/conversations"),
        ("unauthenticated search", "/search?kb_id=1&query=test"),
    ]:
        expect(name, request("GET", path), {401, 403})

    guest_token = login(GUEST_ACCOUNT, GUEST_PASSWORD)
    expect("guest knowledge-base page", request("GET", "/guest/knowledge-bases/page?page=1&page_size=5", token=guest_token), {200})
    for name, path in [
        ("guest platform overview", "/platform/overview"),
        ("guest user page", "/users/page?page=1&page_size=5"),
        ("guest tenant page", "/tenants/page?page=1&page_size=5"),
        ("guest evaluation page", "/platform/evaluations/page?page=1&page_size=5"),
    ]:
        expect(name, request("GET", path, token=guest_token), {403})
    print("documented API smoke cases passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, KeyError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
