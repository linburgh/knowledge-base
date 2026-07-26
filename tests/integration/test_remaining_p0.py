"""Run the remaining P0 organization and knowledge-base dependency cases."""

from __future__ import annotations

import os
import time

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


def main() -> int:
    token = login(os.environ["TEST_ADMIN_ACCOUNT"], os.environ["TEST_ADMIN_PASSWORD"])
    suffix = str(int(time.time()))
    tenant_id: int | None = None
    member_ids: list[int] = []
    root_id: int | None = None
    child_id: int | None = None
    knowledge_base_id: int | None = None
    document_id: int | None = None
    conversation_id: int | None = None

    try:
        users: list[int] = []
        for username in ("e2e_eval_admin_20260726", "e2e_eval_guest_20260726"):
            page = expect(
                f"find P0 fixture user {username}",
                request(
                    "GET",
                    f"/users/page?username={username}&page=1&page_size=5",
                    token=token,
                ),
                {200},
            ).body
            users.append(int(next(row["id"] for row in page.get("rows") or [])))

        tenant = expect(
            "create organization P0 tenant",
            request(
                "POST",
                "/tenants",
                token=token,
                body={"code": f"p0-org-{suffix}", "name": f"P0组织租户-{suffix}"},
            ),
            {201},
        ).body
        tenant_id = int(tenant["id"])
        for user_id in users:
            member = expect(
                "add organization fixture tenant member",
                request(
                    "POST",
                    f"/tenants/{tenant_id}/members",
                    token=token,
                    body={"user_id": user_id, "role_code": "tenant_member"},
                ),
                {201},
            ).body
            member_ids.append(int(member["id"]))

        root = expect(
            "create organization root",
            request(
                "POST",
                "/organizations",
                token=token,
                body={"tenant_id": tenant_id, "code": f"root-{suffix}", "name": "P0根组织"},
            ),
            {201},
        ).body
        root_id = int(root["id"])
        child = expect(
            "create organization child",
            request(
                "POST",
                "/organizations",
                token=token,
                body={
                    "tenant_id": tenant_id,
                    "parent_id": root_id,
                    "code": f"child-{suffix}",
                    "name": "P0子组织",
                },
            ),
            {201},
        ).body
        child_id = int(child["id"])
        expect(
            "organization cycle rejected",
            request("PUT", f"/organizations/{root_id}", token=token, body={"parent_id": child_id}),
            {400},
        )
        root_after_cycle = expect(
            "organization cycle leaves parent unchanged",
            request("GET", f"/organizations/{root_id}", token=token),
            {200},
        ).body
        assert root_after_cycle["parent_id"] is None
        expect(
            "organization with child cannot be deleted",
            request("DELETE", f"/organizations/{root_id}", token=token),
            {400},
        )
        expect(
            "organization batch failure rolls back",
            request(
                "PUT",
                f"/organizations/{child_id}/members/batch",
                token=token,
                body={"members": [{"user_id": users[0]}, {"user_id": 999999999}]},
            ),
            {400, 404},
        )
        members_after_failure = expect(
            "organization batch rollback leaves no partial members",
            request("GET", f"/organizations/{child_id}/members/page?page=1&page_size=20", token=token),
            {200},
        ).body
        assert int(members_after_failure["total"]) == 0
        expect(
            "organization batch add succeeds",
            request(
                "PUT",
                f"/organizations/{child_id}/members/batch",
                token=token,
                body={"members": [{"user_id": user_id} for user_id in users]},
            ),
            {200},
        )

        knowledge_base = expect(
            "create knowledge-base dependency fixture",
            request(
                "POST",
                "/knowledge-bases",
                token=token,
                body={
                    "tenant_id": tenant_id,
                    "name": f"P0删除依赖知识库-{suffix}",
                    "owner_id": str(users[0]),
                },
            ),
            {201},
        ).body
        knowledge_base_id = int(knowledge_base["id"])
        document = expect(
            "create knowledge-base document dependency",
            request(
                "POST",
                "/documents",
                token=token,
                body={
                    "kb_id": knowledge_base_id,
                    "source_type": "test",
                    "source_name": f"p0-{suffix}.md",
                    "content_type": "text/markdown",
                    "object_path": f"tests/p0/{suffix}.md",
                    "file_size": 12,
                    "content_hash": f"p0-{suffix}",
                    "created_by": str(users[0]),
                },
            ),
            {201},
        ).body
        document_id = int(document["id"])
        conversation = expect(
            "create knowledge-base conversation dependency",
            request(
                "POST",
                "/conversations",
                token=token,
                body={"kb_id": knowledge_base_id, "user_id": str(users[0]), "title": "P0依赖会话"},
            ),
            {201},
        ).body
        conversation_id = int(conversation["id"])
        expect(
            "knowledge-base with document and conversation cannot be deleted",
            request("DELETE", f"/knowledge-bases/{knowledge_base_id}", token=token),
            {409},
        )
        expect(
            "remove knowledge-base conversation dependency",
            request("DELETE", f"/conversations/{conversation_id}", token=token),
            {200},
        )
        conversation_id = None
        expect(
            "remove knowledge-base document dependency",
            request("DELETE", f"/documents/{document_id}", token=token),
            {200},
        )
        document_id = None
        expect(
            "delete knowledge-base after dependencies removed",
            request("DELETE", f"/knowledge-bases/{knowledge_base_id}", token=token),
            {200},
        )
        knowledge_base_id = None
        print("remaining P0 organization and knowledge-base dependency cases passed")
        return 0
    finally:
        if conversation_id is not None:
            request("DELETE", f"/conversations/{conversation_id}", token=token)
        if document_id is not None:
            request("DELETE", f"/documents/{document_id}", token=token)
        if knowledge_base_id is not None:
            request("DELETE", f"/knowledge-bases/{knowledge_base_id}", token=token)
        if child_id is not None:
            request("DELETE", f"/organizations/{child_id}", token=token)
        if root_id is not None:
            request("DELETE", f"/organizations/{root_id}", token=token)
        for member_id in member_ids:
            if tenant_id is not None:
                request("DELETE", f"/tenants/{tenant_id}/members/{member_id}", token=token)
        if tenant_id is not None:
            request("DELETE", f"/tenants/{tenant_id}", token=token)


if __name__ == "__main__":
    raise SystemExit(main())
