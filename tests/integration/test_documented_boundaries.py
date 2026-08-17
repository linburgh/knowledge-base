"""Execute low-risk boundary and validation cases from the platform test docs."""

from __future__ import annotations

import os
import time

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


def main() -> int:
    token = login(os.getenv("TEST_ADMIN_ACCOUNT"), os.getenv("TEST_ADMIN_PASSWORD"))
    suffix = str(int(time.time()))
    tenant_id: int | None = None
    user_id: int | None = None
    organization_id: int | None = None

    available_users = expect(
        "knowledge-base available users",
        request("GET", "/knowledge-bases/34/users/available?page=1&page_size=5", token=token),
        {200},
    ).body
    available_rows = available_users.get("rows") or []
    if available_rows and any("password_hash" in row for row in available_rows):
        raise AssertionError("available users response leaked password_hash")
    print("PASS available users response excludes password_hash")

    # Authorization CRUD must enforce tenant membership, uniqueness and cleanup.
    granted_user_id: int | None = None
    granted_organization_id: int | None = None
    if available_rows:
        granted_user_id = int(available_rows[0]["id"])
        expect(
            "knowledge-base grant user",
            request("POST", "/knowledge-bases/34/users", token=token, body={"user_id": granted_user_id}),
            {201},
        )
        expect(
            "duplicate knowledge-base user grant rejected",
            request("POST", "/knowledge-bases/34/users", token=token, body={"user_id": granted_user_id}),
            {409},
        )
        expect(
            "revoke knowledge-base user",
            request("DELETE", f"/knowledge-bases/34/users/{granted_user_id}", token=token),
            {200},
        )
    expect(
        "cross-tenant knowledge-base user grant rejected",
        request("POST", "/knowledge-bases/34/users", token=token, body={"user_id": 211}),
        {400, 404},
    )

    available_organizations = expect(
        "knowledge-base available organizations",
        request("GET", "/knowledge-bases/34/organizations/available?page=1&page_size=5", token=token),
        {200},
    ).body
    organization_rows = available_organizations.get("rows") or []
    if organization_rows:
        granted_organization_id = int(organization_rows[0]["id"])
        expect(
            "knowledge-base grant organization",
            request("POST", "/knowledge-bases/34/organizations", token=token, body={"organization_id": granted_organization_id}),
            {201},
        )
        expect(
            "duplicate knowledge-base organization grant rejected",
            request("POST", "/knowledge-bases/34/organizations", token=token, body={"organization_id": granted_organization_id}),
            {409},
        )
        expect(
            "revoke knowledge-base organization",
            request("DELETE", f"/knowledge-bases/34/organizations/{granted_organization_id}", token=token),
            {200},
        )
    expect(
        "cross-tenant knowledge-base organization grant rejected",
        request("POST", "/knowledge-bases/34/organizations", token=token, body={"organization_id": 205}),
        {400, 404},
    )

    member_candidates = expect(
        "organization member candidates page",
        request("GET", "/organizations/3/member-candidates/page?page=1&page_size=5", token=token),
        {200},
    ).body
    candidate_rows = member_candidates.get("rows") or []
    if candidate_rows and any("password_hash" in row for row in candidate_rows):
        raise AssertionError("organization member candidates leaked password_hash")
    if candidate_rows:
        candidate_user_id = int(candidate_rows[0]["id"])
        member = expect(
            "organization member add",
            request("POST", "/organizations/3/members", token=token, body={"user_id": candidate_user_id}),
            {201},
        ).body
        member_id = int(member["id"])
        try:
            expect(
                "duplicate organization member rejected",
                request("POST", "/organizations/3/members", token=token, body={"user_id": candidate_user_id}),
                {409},
            )
            expect(
                "organization member modify",
                request(
                    "PUT",
                    f"/organizations/3/members/{member_id}",
                    token=token,
                    body={"status": "disabled", "role_code": "org_member"},
                ),
                {200},
            )
        finally:
            expect(
                "organization member remove",
                request("DELETE", f"/organizations/3/members/{member_id}", token=token),
                {200},
            )
    print("PASS organization member candidate response excludes password_hash")

    dependency_tenant = expect(
        "tenant dependency probe create",
        request(
            "POST",
            "/tenants",
            token=token,
            body={"code": f"dependency-{suffix}", "name": f"删除约束探针-{suffix}"},
        ),
        {201},
    ).body
    dependency_tenant_id = int(dependency_tenant["id"])
    dependency_kb_id: int | None = None
    try:
        dependency_kb_id = int(
            expect(
                "tenant dependency probe knowledge base",
                request(
                    "POST",
                    "/knowledge-bases",
                    token=token,
                    body={
                        "tenant_id": dependency_tenant_id,
                        "name": f"删除约束探针知识库-{suffix}",
                        "owner_id": "204",
                    },
                ),
                {201},
            ).body["id"]
        )
        expect(
            "tenant with active knowledge base cannot be deleted",
            request("DELETE", f"/tenants/{dependency_tenant_id}", token=token),
            {409},
        )
    finally:
        if dependency_kb_id is not None:
            expect(
                "delete dependency probe knowledge base",
                request("DELETE", f"/knowledge-bases/{dependency_kb_id}", token=token),
                {200},
            )
        expect(
            "delete dependency probe tenant",
            request("DELETE", f"/tenants/{dependency_tenant_id}", token=token),
            {200},
        )

    # Duplicate tenant codes must be rejected without replacing the first row.
    tenant_payload = {
        "code": f"boundary-{suffix}",
        "name": f"边界测试租户-{suffix}",
    }
    tenant = expect("boundary create tenant", request("POST", "/tenants", token=token, body=tenant_payload), {201}).body
    tenant_id = int(tenant["id"])
    try:
        expect("duplicate tenant code rejected", request("POST", "/tenants", token=token, body=tenant_payload), {409})

        # Required-field and format validation must fail before persistence.
        expect("tenant missing name rejected", request("POST", "/tenants", token=token, body={"code": f"missing-{suffix}"}), {422})
        expect("user missing username rejected", request("POST", "/users", token=token, body={"email": f"missing-{suffix}@example.com"}), {422})
        expect(
            "invalid user email rejected",
            request(
                "POST",
                "/users",
                token=token,
                body={"username": f"invalidemail{suffix}", "email": "not-an-email", "password": "test-password-123"},
            ),
            {400, 422},
        )

        user_payload = {
            "username": f"boundary{suffix}",
            "email": f"boundary{suffix}@example.com",
            "display_name": "边界测试用户",
            "password": "test-password-123",
        }
        user = expect("boundary create user", request("POST", "/users", token=token, body=user_payload), {201}).body
        user_id = int(user["id"])
        try:
            expect("duplicate username rejected", request("POST", "/users", token=token, body={**user_payload, "email": f"other-{suffix}@example.com"}), {409})
            expect("short password rejected", request("POST", "/users", token=token, body={"username": f"short{suffix}", "password": "short"}), {422})

            organization = expect(
                "boundary create organization",
                request("POST", "/organizations", token=token, body={"tenant_id": tenant_id, "code": f"org-{suffix}", "name": "边界测试组织"}),
                {201},
            ).body
            organization_id = int(organization["id"])
            try:
                expect(
                    "organization self parent rejected",
                    request("PUT", f"/organizations/{organization_id}", token=token, body={"parent_id": organization_id}),
                    {400, 409},
                )
                expect(
                    "organization missing name rejected",
                    request("POST", "/organizations", token=token, body={"tenant_id": tenant_id, "code": f"missing-org-{suffix}"}),
                    {422},
                )
            finally:
                expect("delete boundary organization", request("DELETE", f"/organizations/{organization_id}", token=token), {200})
                organization_id = None

            # Evaluation execution.user_id is a numeric database ID, not an account name.
            expect(
                "evaluation account name rejected as user id",
                request(
                    "POST",
                    "/platform/evaluations",
                    token=token,
                    body={
                        "name": f"边界评测-{suffix}",
                        "kb_id": 34,
                        "questions_content": "问题\t答案\n测试问题\t测试答案",
                        "execution": {"user_id": "linburgh"},
                    },
                ),
                {400, 422},
            )
        finally:
            expect("delete boundary user", request("DELETE", f"/users/{user_id}", token=token), {200})
            user_id = None
    finally:
        if organization_id is not None:
            request("DELETE", f"/organizations/{organization_id}", token=token)
        if user_id is not None:
            request("DELETE", f"/users/{user_id}", token=token)
        expect("delete boundary tenant", request("DELETE", f"/tenants/{tenant_id}", token=token), {200})

    print("documented boundary cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
