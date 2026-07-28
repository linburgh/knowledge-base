"""Executable permission and tenant-scope tests for the tenant-admin role."""

from __future__ import annotations

import os
import sys

try:
    from .test_documented_api_smoke import expect, login, request
except ImportError:
    from test_documented_api_smoke import expect, login, request


ACCOUNT = os.getenv("TENANT_ADMIN_ACCOUNT", "tenant-admin-acc")
PASSWORD = os.getenv("TENANT_ADMIN_PASSWORD", "tenant-owner-acc")
TENANT_ID = int(os.getenv("TENANT_ADMIN_TENANT_ID", "151"))

EXPECTED_MENU_CODES = {
    "platform",
    "platform_overview",
    "platform_users",
    "platform_organizations",
    "platform_evaluations",
    "knowledge_base",
    "knowledge_base_list",
    "knowledge_base_workspace",
    "knowledge_base_overview",
    "knowledge_base_documents",
    "knowledge_base_chat",
}
FORBIDDEN_MENU_CODES = {"developer_api", "platform_tenants"}
FORBIDDEN_ACTION_CODES = {
    "tenant:list",
    "tenant:create",
    "tenant:update",
    "tenant:delete",
    "tenant:member",
}
EXPECTED_ACTION_CODES = {
    "platform_overview:view",
    "platform_user:list",
    "platform_user:create",
    "platform_user:update",
    "platform_user:delete",
    "platform_user:role",
    "organization:list",
    "organization:create",
    "organization:update",
    "organization:delete",
    "organization:member",
    "evaluation:list",
    "evaluation:create",
    "evaluation:update",
    "evaluation:execute",
    "evaluation:detail",
    "evaluation:delete",
    "evaluation:optimize",
    "knowledge_base:list",
    "knowledge_base:create",
    "knowledge_base:update",
    "knowledge_base:delete",
    "knowledge_base:member",
    "knowledge_base:overview",
    "knowledge_base:update_config",
    "document:list",
    "document:upload",
    "document:delete",
    "document:reindex",
    "knowledge_base:ask",
}


def flatten_menu_codes(nodes: list[dict]) -> set[str]:
    result: set[str] = set()
    for node in nodes:
        result.add(node["code"])
        result.update(flatten_menu_codes(node.get("children", [])))
    return result


def main() -> int:
    token = login(ACCOUNT, PASSWORD)

    context = expect(
        "tenant_admin auth context",
        request("GET", "/auth/me", token=token),
        {200},
    ).body
    assert context["tenant_role"] == "tenant_admin", context
    assert int(context["current_tenant"]["id"]) == TENANT_ID, context

    menu_response = expect(
        "tenant_admin menus",
        request("GET", "/auth/menus", token=token),
        {200},
    ).body
    menu_codes = flatten_menu_codes(menu_response["menus"])
    assert menu_codes == EXPECTED_MENU_CODES, sorted(menu_codes)
    assert not menu_codes & FORBIDDEN_MENU_CODES, sorted(menu_codes & FORBIDDEN_MENU_CODES)

    permissions = expect(
        "tenant_admin permissions",
        request("GET", "/auth/permissions", token=token),
        {200},
    ).body
    action_codes = set(permissions["action_codes"])
    assert EXPECTED_ACTION_CODES <= action_codes, sorted(EXPECTED_ACTION_CODES - action_codes)
    assert not action_codes & FORBIDDEN_ACTION_CODES, sorted(action_codes & FORBIDDEN_ACTION_CODES)
    assert "developer_api:view" not in action_codes, sorted(action_codes)

    checks = expect(
        "tenant_admin permission check",
        request(
            "POST",
            "/auth/permissions/check",
            token=token,
            body={
                "action_codes": sorted(
                    EXPECTED_ACTION_CODES
                    | FORBIDDEN_ACTION_CODES
                    | {"developer_api:view"}
                )
            },
        ),
        {200},
    ).body
    check_map = {item["action_code"]: item["allowed"] for item in checks["items"]}
    assert all(check_map[code] for code in EXPECTED_ACTION_CODES)
    assert all(not check_map[code] for code in FORBIDDEN_ACTION_CODES)
    assert check_map["developer_api:view"] is False

    expect(
        "tenant_admin current tenant selection",
        request("POST", "/auth/tenant", token=token, body={"tenant_id": TENANT_ID}),
        {200},
    )
    expect(
        "tenant_admin cross-tenant selection rejected",
        request("POST", "/auth/tenant", token=token, body={"tenant_id": 3}),
        {403},
    )

    overview = expect(
        "tenant_admin platform overview",
        request("GET", "/platform/overview", token=token),
        {200},
    ).body
    assert "tenant_total" in overview["metrics"]
    assert "active_tenant_total" in overview["metrics"]
    non_business_actions = {"login", "logout", "refresh_token", "select_tenant"}
    assert not any(
        item["action"] in non_business_actions
        for item in overview["recent_activities"]
    )
    assert all(
        int(item["tenant_id"]) == TENANT_ID
        for item in overview["tenant_resources"]
    )

    users = expect(
        "tenant_admin user page",
        request("GET", "/users/page?page=1&page_size=5", token=token),
        {200},
    ).body
    assert users["total"] >= 1
    evaluations = expect(
        "tenant_admin evaluation page",
        request("GET", "/platform/evaluations/page?page=1&page_size=5", token=token),
        {200},
    ).body
    assert all(int(item["tenant_id"]) == TENANT_ID for item in evaluations["items"])
    expect(
        "tenant_admin organization tree",
        request("GET", f"/organizations/tree?tenant_id={TENANT_ID}", token=token),
        {200},
    )
    parent_page = expect(
        "tenant_admin organization parent cursor page",
        request("GET", f"/organizations/tree/parents?tenant_id={TENANT_ID}&page_size=5", token=token),
        {200},
    ).body
    assert {"items", "next_cursor", "has_more"} <= set(parent_page)
    assert all(int(item["tenant_id"]) == TENANT_ID for item in parent_page["items"])
    if parent_page["items"]:
        parent_id = parent_page["items"][0]["id"]
        child_page = expect(
            "tenant_admin organization child cursor page",
            request("GET", f"/organizations/{parent_id}/children?page_size=5", token=token),
            {200},
        ).body
        assert {"items", "next_cursor", "has_more"} <= set(child_page)
        assert all(int(item["tenant_id"]) == TENANT_ID for item in child_page["items"])
    expect(
        "tenant_admin cross-tenant organization tree rejected",
        request("GET", "/organizations/tree?tenant_id=3", token=token),
        {403},
    )
    expect(
        "tenant_admin cross-tenant organization parent cursor rejected",
        request("GET", "/organizations/tree/parents?tenant_id=3", token=token),
        {403},
    )

    assert menu_response["default_path"] == "/platform/overview"
    print("tenant_admin menu and operation permission cases passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, RuntimeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
