"""Run the P0 tenant dependency, status and isolation cases with disposable data."""

from __future__ import annotations

import os
import time

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


def main() -> int:
    admin_account = os.environ["TEST_ADMIN_ACCOUNT"]
    admin_password = os.environ["TEST_ADMIN_PASSWORD"]
    guest_account = os.environ["TEST_GUEST_ACCOUNT"]
    guest_password = os.environ["TEST_GUEST_PASSWORD"]
    admin_token = login(admin_account, admin_password)
    suffix = str(int(time.time()))
    tenant_id: int | None = None
    member_id: int | None = None
    user_id: int | None = None
    organization_id: int | None = None
    knowledge_base_id: int | None = None
    knowledge_base_user_id: int | None = None

    try:
        user_page = expect(
            "find disposable guest user",
            request(
                "GET",
                f"/users/page?username={guest_account}&page=1&page_size=5",
                token=admin_token,
            ),
            {200},
        ).body
        user_rows = user_page.get("rows") or []
        user_id = int(next(row["id"] for row in user_rows if row["username"] == guest_account))

        tenant = expect(
            "create P0 disposable tenant",
            request(
                "POST",
                "/tenants",
                token=admin_token,
                body={"code": f"p0-tenant-{suffix}", "name": f"P0租户探针-{suffix}"},
            ),
            {201},
        ).body
        tenant_id = int(tenant["id"])

        member = expect(
            "add active tenant member dependency",
            request(
                "POST",
                f"/tenants/{tenant_id}/members",
                token=admin_token,
                body={"user_id": user_id, "role_code": "tenant_guest", "is_primary": True},
            ),
            {201},
        ).body
        member_id = int(member["id"])

        organization = expect(
            "create active organization dependency",
            request(
                "POST",
                "/organizations",
                token=admin_token,
                body={
                    "tenant_id": tenant_id,
                    "code": f"p0-org-{suffix}",
                    "name": f"P0组织探针-{suffix}",
                },
            ),
            {201},
        ).body
        organization_id = int(organization["id"])

        knowledge_base = expect(
            "create active knowledge-base dependency",
            request(
                "POST",
                "/knowledge-bases",
                token=admin_token,
                body={
                    "tenant_id": tenant_id,
                    "name": f"P0知识库探针-{suffix}",
                    "owner_id": str(user_id),
                },
            ),
            {201},
        ).body
        knowledge_base_id = int(knowledge_base["id"])
        grant = expect(
            "grant disposable guest knowledge-base access",
            request(
                "POST",
                f"/knowledge-bases/{knowledge_base_id}/users",
                token=admin_token,
                body={"user_id": user_id},
            ),
            {201},
        ).body
        knowledge_base_user_id = user_id

        expect(
            "delete tenant with member organization and knowledge-base rejected",
            request("DELETE", f"/tenants/{tenant_id}", token=admin_token),
            {409},
        )
        still_active = expect(
            "tenant dependency rejection preserves tenant",
            request("GET", f"/tenants/{tenant_id}", token=admin_token),
            {200},
        ).body
        assert still_active["status"] != "deleted"
        assert still_active["member_count"] >= 1
        assert still_active["organization_count"] >= 1
        assert still_active["knowledge_base_count"] >= 1
        print("PASS dependency rejection preserves all three dependency counts")

        guest_token = login(guest_account, guest_password)
        expect("guest sees disposable tenant", request("GET", "/auth/tenants", token=guest_token), {200})
        expect(
            "guest can select active disposable tenant",
            request("POST", "/auth/tenant", token=guest_token, body={"tenant_id": tenant_id}),
            {200},
        )
        expect(
            "guest can access tenant knowledge-base",
            request("GET", "/guest/knowledge-bases/page?page=1&page_size=20", token=guest_token),
            {200},
        )
        expect(
            "platform admin can access tenant organizations",
            request("GET", f"/organizations/tree?tenant_id={tenant_id}", token=admin_token),
            {200},
        )

        expect(
            "disable tenant",
            request("PUT", f"/tenants/{tenant_id}", token=admin_token, body={"status": "disabled"}),
            {200},
        )
        disabled_tenants = expect(
            "disabled tenant is not selectable",
            request("GET", "/auth/tenants", token=guest_token),
            {200},
        ).body
        assert not any(int(row["id"]) == tenant_id for row in disabled_tenants)
        expect(
            "disabled tenant selection rejected",
            request("POST", "/auth/tenant", token=guest_token, body={"tenant_id": tenant_id}),
            {403},
        )
        expect(
            "disabled tenant guest resource access rejected",
            request("GET", "/guest/knowledge-bases/page?page=1&page_size=20", token=guest_token),
            {401, 403},
        )

        expect(
            "restore disposable tenant",
            request("PUT", f"/tenants/{tenant_id}", token=admin_token, body={"status": "active"}),
            {200},
        )
        expect(
            "restored tenant selectable",
            request("POST", "/auth/tenant", token=guest_token, body={"tenant_id": tenant_id}),
            {200},
        )
        print("tenant P0 dependency, disabled-access and restore cases passed")
        return 0
    finally:
        if knowledge_base_user_id is not None and knowledge_base_id is not None:
            expect(
                "remove disposable knowledge-base grant",
                request(
                    "DELETE",
                    f"/knowledge-bases/{knowledge_base_id}/users/{knowledge_base_user_id}",
                    token=admin_token,
                ),
                {200},
            )
        if knowledge_base_id is not None:
            expect(
                "delete disposable knowledge-base",
                request("DELETE", f"/knowledge-bases/{knowledge_base_id}", token=admin_token),
                {200},
            )
        if organization_id is not None:
            expect(
                "delete disposable organization",
                request("DELETE", f"/organizations/{organization_id}", token=admin_token),
                {200},
            )
        if member_id is not None and tenant_id is not None:
            expect(
                "remove disposable tenant member",
                request("DELETE", f"/tenants/{tenant_id}/members/{member_id}", token=admin_token),
                {200},
            )
        if tenant_id is not None:
            expect(
                "delete disposable tenant after dependencies removed",
                request("DELETE", f"/tenants/{tenant_id}", token=admin_token),
                {200},
            )


if __name__ == "__main__":
    raise SystemExit(main())
