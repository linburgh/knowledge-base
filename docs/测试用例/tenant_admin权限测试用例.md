# tenant_admin 权限测试用例

## 1. 测试对象

| 项目 | 内容 |
|---|---|
| 测试账号 | `tenant-admin-acc` |
| 角色 | `tenant_admin` |
| 当前租户 | `tenant-owner-test`，租户 ID `151` |
| 测试脚本 | `tests/integration/test_tenant_admin_permissions.py` |
| API 地址 | `http://127.0.0.1:28003/api/v1` |

## 2. 权限期望

`tenant_admin` 应返回平台管理目录及以下四个子菜单：平台概览、用户管理、组织管理、自主评测；不应返回租户管理和开发者中心。知识库菜单按当前配置一并返回。

## 3. 测试用例及结果

| 编号 | 测试场景 | 操作与断言 | 结果 |
|---|---|---|---|
| TO-001 | 身份与租户上下文 | 登录后 `/auth/me` 的租户角色为 `tenant_admin`，当前租户 ID 为 `151` | 通过 |
| TO-002 | 平台管理父菜单 | `/auth/menus` 返回 `platform` 父菜单 | 通过 |
| TO-003 | 平台四个子菜单 | 返回 `platform_overview`、`platform_users`、`platform_organizations`、`platform_evaluations` | 通过 |
| TO-004 | 租户管理隔离 | `/auth/menus` 不返回 `platform_tenants` | 通过 |
| TO-005 | 开发者中心隔离 | `/auth/menus` 不返回 `developer_api` | 通过 |
| TO-006 | 操作权限 | `/auth/permissions` 返回平台四个子菜单及知识库配置的全部操作编码，不返回 `tenant:*` | 通过 |
| TO-007 | 权限批量校验 | `/auth/permissions/check` 对授权操作返回 `allowed=true` | 通过 |
| TO-008 | 未授权操作校验 | `developer_api:view` 和 `tenant:list` 返回 `allowed=false` | 通过 |
| TO-009 | 默认入口 | 菜单接口 `default_path` 为 `/platform/overview` | 通过 |
| TO-010 | 当前租户边界 | 可选择租户 `151`，选择其他租户 `3` 返回 `403` | 通过 |
| TO-011 | 平台概览接口 | `/platform/overview` 返回 `200`，统计和租户资源仅包含租户 `151` | 通过 |
| TO-012 | 用户管理列表 | `/users/page` 返回 `200`，当前租户用户可正常加载 | 通过 |
| TO-013 | 自主评测列表 | `/platform/evaluations/page` 返回 `200`，只返回当前租户任务 | 通过 |
| TO-014 | 组织管理树 | 当前租户组织树返回 `200`，跨租户组织树返回 `403` | 通过 |

## 4. 执行命令

```bash
.venv/bin/python tests/integration/test_tenant_admin_permissions.py
```

## 5. 执行结果

执行结果：通过。

实际输出包含 4 个 HTTP 接口检查和默认入口断言，全部通过：

- `/auth/me`：通过
- `/auth/menus`：通过
- `/auth/permissions`：通过
- `/auth/permissions/check`：通过
- 当前租户选择和跨租户拒绝：通过
- `/platform/overview`：通过，返回数据仅包含租户 `151`
- `/users/page`：通过
- `/organizations/tree`：通过，跨租户查询返回 `403`
- `/platform/evaluations/page`：通过，任务按当前租户隔离
- `/platform/overview` 默认入口：通过
