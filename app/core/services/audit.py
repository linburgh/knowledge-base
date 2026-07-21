from __future__ import annotations

from typing import Any

from app.core.common import audit as audit_context
from app.db import audit_log as audit_log_db


ACTION_CN_MAP: dict[str, str] = {
    "add_organization_member": "添加组织成员",
    "add_tenant_member": "添加租户成员",
    "assign_platform_roles": "分配平台角色",
    "batch_grant_knowledge_base_organizations": "批量授权知识库组织",
    "batch_grant_knowledge_base_users": "批量授权知识库用户",
    "batch_add_tenant_members": "批量添加租户成员",
    "bind_tenant_organizations": "绑定租户组织",
    "bind_tenant_knowledge_bases": "绑定租户知识库",
    "batch_update_organization_members": "批量调整组织成员",
    "创建知识库": "创建知识库",
    "创建组织": "创建组织",
    "create_document": "创建文档",
    "create_knowledge_base": "创建知识库",
    "create_organization": "创建组织",
    "create_tenant": "创建租户",
    "create_user": "创建用户",
    "delete_document": "删除文档",
    "delete_knowledge_base": "删除知识库",
    "delete_organization": "删除组织",
    "delete_tenant": "删除租户",
    "delete_user": "删除用户",
    "login": "登录",
    "logout": "退出登录",
    "加入租户": "加入租户",
    "refresh_token": "刷新令牌",
    "remove_organization_member": "移除组织成员",
    "remove_tenant_member": "移除租户成员",
    "select_tenant": "选择租户",
    "完成文档索引": "完成文档索引",
    "新增用户": "新增用户",
    "update_document": "修改文档",
    "update_knowledge_base": "修改知识库",
    "update_organization": "修改组织",
    "update_organization_member": "修改组织成员",
    "update_tenant": "修改租户",
    "update_tenant_member": "修改租户成员",
    "update_user": "修改用户",
}


def action_cn(action: str) -> str:
    return ACTION_CN_MAP.get(action, "其他操作")


async def record(
    db,
    *,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    result: str = "success",
    error_message: str | None = None,
    summary: dict[str, Any] | None = None,
) -> Any:
    context = audit_context.get_context()
    return await audit_log_db.insert_(
        db,
        actor_id=context.get("actor_id") or "system",
        action=action,
        action_cn=action_cn(action),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        request_id=context.get("request_id"),
        request_summary=audit_context.request_summary(summary),
        result=result,
        error_message=error_message,
    )


__all__ = ("record",)
