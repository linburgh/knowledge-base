"""Run P1 platform overview, user boundary and knowledge-base overview cases."""

from __future__ import annotations

import os
import time

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


def main() -> int:
    admin = login(os.environ["TEST_ADMIN_ACCOUNT"], os.environ["TEST_ADMIN_PASSWORD"])
    guest = login(os.environ["TEST_GUEST_ACCOUNT"], os.environ["TEST_GUEST_PASSWORD"])
    suffix = str(int(time.time()))
    user_ids: list[int] = []
    tenant_id: int | None = None
    kb_id: int | None = None

    try:
        for range_name in ("7d", "30d"):
            overview = expect(
                f"platform overview {range_name}",
                request("GET", f"/platform/overview?range={range_name}", token=admin),
                {200},
            ).body
            assert overview["range"] == range_name
            assert "metrics" in overview and "user_trend" in overview
            assert len(overview["user_trend"]) > 0
        expect(
            "platform overview explicit date range",
            request(
                "GET",
                "/platform/overview?range=custom&start_at=2026-07-01T00:00:00Z&end_at=2026-07-03T00:00:00Z",
                token=admin,
            ),
            {200},
        )
        expect(
            "platform overview invalid tenant limit rejected",
            request("GET", "/platform/overview?tenant_limit=0", token=admin),
            {422},
        )
        expect("guest platform overview forbidden", request("GET", "/platform/overview", token=guest), {403})

        temp_tenant = expect(
            "create P1 overview tenant",
            request(
                "POST",
                "/tenants",
                token=admin,
                body={"code": f"p1-overview-{suffix}", "name": f"P1概览租户-{suffix}"},
            ),
            {201},
        ).body
        tenant_id = int(temp_tenant["id"])
        users = []
        for index in (1, 2):
            user = expect(
                f"create P1 user {index}",
                request(
                    "POST",
                    "/users",
                    token=admin,
                    body={
                        "username": f"p1user{suffix}{index}",
                        "email": f"p1user{suffix}{index}@example.test",
                        "display_name": f"P1用户{index}",
                        "password": "P1-test-password",
                    },
                ),
                {201},
            ).body
            users.append(int(user["id"]))
            user_ids.append(int(user["id"]))
        expect(
            "duplicate email rejected",
            request(
                "POST",
                "/users",
                token=admin,
                body={
                    "username": f"p1duplicate{suffix}",
                    "email": f"p1user{suffix}1@example.test",
                    "password": "P1-test-password",
                },
            ),
            {409},
        )
        expect(
            "guest cannot call user management",
            request("PUT", f"/users/{users[0]}", token=guest, body={"status": "disabled"}),
            {403},
        )

        member = expect(
            "add P1 guest tenant membership",
            request(
                "POST",
                f"/tenants/{tenant_id}/members",
                token=admin,
                body={"user_id": users[0], "role_code": "tenant_member"},
            ),
            {201},
        ).body
        member_id = int(member["id"])
        kb = expect(
            "create empty P1 knowledge-base",
            request(
                "POST",
                "/knowledge-bases",
                token=admin,
                body={"tenant_id": tenant_id, "name": f"P1空知识库-{suffix}", "owner_id": str(users[0])},
            ),
            {201},
        ).body
        kb_id = int(kb["id"])
        kb_overview = expect(
            "empty knowledge-base overview",
            request("GET", f"/knowledge-bases/{kb_id}/overview?range=30d", token=admin),
            {200},
        ).body
        assert kb_overview["metrics"]["document_total"] == 0
        assert kb_overview["metrics"]["chunk_total"] == 0
        expect(
            "knowledge-base cross-tenant overview forbidden",
            request("GET", f"/knowledge-bases/{kb_id}/overview", token=guest),
            {403, 404},
        )
        expect(
            "knowledge-base overview invalid range rejected",
            request("GET", f"/knowledge-bases/{kb_id}/overview?range=invalid", token=admin),
            {400, 422},
        )

        # Verify the current-user disable path using a disposable account.
        guest_user = expect(
            "create disposable current-user account",
            request(
                "POST",
                "/users",
                token=admin,
                body={
                    "username": f"p1current{suffix}",
                    "email": f"p1current{suffix}@example.test",
                    "password": "P1-test-password",
                },
            ),
            {201},
        ).body
        guest_user_id = int(guest_user["id"])
        user_ids.append(guest_user_id)
        # A disabled account cannot log in; this is the authentication boundary.
        expect(
            "disable disposable current-user account",
            request("PUT", f"/users/{guest_user_id}", token=admin, body={"status": "disabled"}),
            {200},
        )
        expect(
            "disabled account login rejected",
            request("POST", "/auth/login", body={"account": f"p1current{suffix}", "password": "P1-test-password"}),
            {401},
        )
        print("P1 platform, user and knowledge-base overview cases passed")
        return 0
    finally:
        if kb_id is not None:
            request("DELETE", f"/knowledge-bases/{kb_id}", token=admin)
        if tenant_id is not None:
            # The only active tenant member added here is removed before tenant cleanup.
            members = request("GET", f"/tenants/{tenant_id}/members/page?page=1&page_size=20", token=admin)
            for row in (members.body or {}).get("rows", []):
                request("DELETE", f"/tenants/{tenant_id}/members/{row['id']}", token=admin)
            request("DELETE", f"/tenants/{tenant_id}", token=admin)
        for user_id in user_ids:
            request("DELETE", f"/users/{user_id}", token=admin)


if __name__ == "__main__":
    raise SystemExit(main())
