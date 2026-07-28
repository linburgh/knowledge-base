from __future__ import annotations

from typing import Any

from app.types.constants import PLATFORM_ROLE_SUPER_ADMIN

ROLE_PRIORITY = {
    PLATFORM_ROLE_SUPER_ADMIN: 300,
    "tenant_admin": 200,
    "tenant_member": 100,
    "tenant_guest": 50,
}


def active_platform_role_codes(context: dict[str, Any] | None) -> set[str]:
    return {
        str(role.get("code"))
        for role in (context or {}).get("platform_roles", [])
        if role.get("code") and role.get("status", "active") == "active"
    }


def effective_role(context: dict[str, Any] | None) -> str | None:
    candidates: list[str] = list(active_platform_role_codes(context))
    tenant_role = (context or {}).get("tenant_role")
    if tenant_role:
        candidates.append(str(tenant_role))
    candidates.extend(
        str(organization.get("role_code"))
        for organization in (context or {}).get("organizations", [])
        if organization.get("role_code")
    )
    if not candidates:
        return None
    return max(candidates, key=lambda role: ROLE_PRIORITY.get(role, 0))


def is_platform_super_admin(context: dict[str, Any] | None) -> bool:
    return effective_role(context) == PLATFORM_ROLE_SUPER_ADMIN


__all__ = (
    "ROLE_PRIORITY",
    "active_platform_role_codes",
    "effective_role",
    "is_platform_super_admin",
)
