"""HTTP performance checks for the cursor-paginated organization tree."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.parse
import urllib.request

BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:28003/api/v1").rstrip("/")


def request(method: str, path: str, *, token: str, params: dict | None = None) -> tuple[int, dict, float]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request_obj = urllib.request.Request(
        f"{BASE_URL}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
        method=method,
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request_obj, timeout=120) as response:
        body = json.loads(response.read().decode())
    return response.status, body, time.perf_counter() - started


def login(account: str, password: str) -> str:
    request_obj = urllib.request.Request(
        f"{BASE_URL}/auth/login",
        data=json.dumps({"account": account, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request_obj, timeout=30) as response:
        return str(json.loads(response.read().decode())["access_token"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--account", default=os.getenv("TEST_ADMIN_ACCOUNT", "linburgh"))
    parser.add_argument("--password", default=os.getenv("TEST_ADMIN_PASSWORD", "linburgh"))
    args = parser.parse_args()
    token = login(args.account, args.password)

    status, parents, parent_seconds = request(
        "GET",
        "/organizations/tree/parents",
        token=token,
        params={"tenant_id": args.tenant_id, "page_size": 20},
    )
    assert status == 200, parents
    assert len(parents["items"]) > 0, "性能测试租户没有根节点"
    root_id = int(parents["items"][0]["id"])

    status, children, child_seconds = request(
        "GET",
        f"/organizations/{root_id}/children",
        token=token,
        params={"page_size": 20},
    )
    assert status == 200, children
    assert len(children["items"]) >= 1, children

    depth_seconds: list[float] = []
    current_node_id = int(children["items"][0]["id"])
    for _ in range(9):
        status, depth_page, elapsed = request(
            "GET",
            f"/organizations/{current_node_id}/children",
            token=token,
            params={"page_size": 1},
        )
        assert status == 200, depth_page
        assert depth_page["items"], "组织树链路未达到 10 级"
        current_node_id = int(depth_page["items"][0]["id"])
        depth_seconds.append(elapsed)

    next_cursor = children["next_cursor"]
    continuation_seconds: list[float] = []
    for _ in range(5):
        if not next_cursor:
            break
        status, page, elapsed = request(
            "GET",
            f"/organizations/{root_id}/children",
            token=token,
            params={"page_size": 20, "cursor": next_cursor},
        )
        assert status == 200, page
        continuation_seconds.append(elapsed)
        next_cursor = page["next_cursor"]

    concurrent_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                request,
                "GET",
                "/organizations/tree/parents",
                token=token,
                params={"tenant_id": args.tenant_id, "page_size": 20},
            )
            for _ in range(8)
        ]
        concurrent_results = [future.result() for future in futures]
    concurrent_elapsed = time.perf_counter() - concurrent_started
    assert all(status == 200 for status, _, _ in concurrent_results)

    print(f"parent_first_page_seconds={parent_seconds:.3f}")
    print(f"child_first_page_seconds={child_seconds:.3f}")
    print(f"depth_10_level_seconds={[round(value, 3) for value in depth_seconds]}")
    print(f"child_continuation_seconds={[round(value, 3) for value in continuation_seconds]}")
    print(f"concurrent_8_requests_seconds={concurrent_elapsed:.3f}")


if __name__ == "__main__":
    main()
