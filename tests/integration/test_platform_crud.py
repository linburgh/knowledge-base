"""Destructive-looking platform CRUD cases using isolated temporary records."""

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

    tenant = expect(
        "create temporary tenant",
        request(
            "POST",
            "/tenants",
            token=token,
            body={
                "code": f"test-crud-{suffix}",
                "name": f"测试临时租户-{suffix}",
                "description": "automated documented test",
            },
        ),
        {201},
    ).body
    tenant_id = int(tenant["id"])
    try:
        expect("get temporary tenant", request("GET", f"/tenants/{tenant_id}", token=token), {200})
        expect(
            "modify temporary tenant",
            request("PUT", f"/tenants/{tenant_id}", token=token, body={"name": f"测试临时租户-已修改-{suffix}"}),
            {200},
        )

        user = expect(
            "create temporary user",
            request(
                "POST",
                "/users",
                token=token,
                body={
                    "username": f"testcrud{suffix}",
                    "email": f"testcrud{suffix}@example.com",
                    "display_name": "测试临时用户",
                    "password": "test-password-123",
                },
            ),
            {201},
        ).body
        user_id = int(user["id"])
        try:
            expect(
                "modify temporary user",
                request("PUT", f"/users/{user_id}", token=token, body={"display_name": "测试临时用户-已修改", "status": "active"}),
                {200},
            )

            organization = expect(
                "create temporary organization",
                request(
                    "POST",
                    "/organizations",
                    token=token,
                    body={"tenant_id": tenant_id, "code": f"org-{suffix}", "name": f"测试临时组织-{suffix}"},
                ),
                {201},
            ).body
            organization_id = int(organization["id"])
            try:
                expect(
                    "modify temporary organization",
                    request("PUT", f"/organizations/{organization_id}", token=token, body={"name": f"测试临时组织-已修改-{suffix}"}),
                    {200},
                )
                expect(
                    "delete temporary organization",
                    request("DELETE", f"/organizations/{organization_id}", token=token),
                    {200},
                )
            finally:
                # DELETE is idempotent at the business level only when the record exists.
                pass
        finally:
            expect("delete temporary user", request("DELETE", f"/users/{user_id}", token=token), {200})
    finally:
        expect("delete temporary tenant", request("DELETE", f"/tenants/{tenant_id}", token=token), {200})

    print("platform CRUD documented cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
