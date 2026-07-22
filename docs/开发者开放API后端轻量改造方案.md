# 开发者开放 API 后端轻量改造方案

## 1. 方案结论

当前不建设完整的开发者平台，不新增应用、Client Secret、OAuth2、应用授权关系和独立配额体系。

采用以下架构：

```text
外部调用方
    ↓
Nginx
    ├─ /open/* 路径代理
    ├─ 限流、超时、请求体大小、CORS
    ├─ 请求 ID 和内部路径隐藏
    └─ 管理接口隔离
    ↓
FastAPI Open API Facade
    ├─ 复用现有 Bearer Token
    ├─ 覆盖客户端 user_id、created_by
    ├─ 校验知识库访问权限
    └─ 转换开放 API 请求和响应
    ↓
现有 Service / DB / RAG
```

该方案面向企业内部系统和可信租户系统集成。调用身份仍然是平台用户身份，后续如需面向陌生第三方，再增加应用 Token 层，不改变 Facade 的业务接口。

## 2. 改造边界

### 2.1 新增内容

```text
app/api/open/
app/schemas/open.py
app/core/common/access.py
```

Nginx 配置作为部署配置维护，不放入业务 Service。

### 2.2 少量修改内容

- 在 `app/main.py` 或 API 路由注册处增加 Open API 路由前缀。
- 在 `app/core/common/auth.py` 复用现有 Bearer Token 校验，不新增认证协议。
- 在 `app/core/common/exception.py` 和全局异常处理中补充开放 API 响应格式。
- 在检索、问答、会话、文档开放入口调用统一的知识库访问检查。
- 对现有 Service 仅补充必要的 `current_user` 或访问范围参数，不重写业务流程。

### 2.3 明确不做

- 不新增应用表、API Key 表和应用授权表。
- 不改造现有登录、刷新 Token 和用户会话模型。
- 不开放用户、租户、组织、平台管理接口。
- 不在 Nginx 中实现用户权限和知识库权限判断。
- 当前不做应用配额、账单、调用日志和调用分析页面。
- 当前不开放文档索引触发接口。

## 3. Open API 路由

第一阶段使用轻量路径：

```text
/api/v1/open/knowledge-bases
/api/v1/open/search
/api/v1/open/chat
/api/v1/open/conversations/{conversation_id}
/api/v1/open/conversations/{conversation_id}/messages
/api/v1/open/documents/{document_id}
/api/v1/open/documents/{document_id}/tasks/{task_id}
```

暂不使用 `/open/v1`，避免同时引入新版本体系。未来需要对外稳定发布时，可以由 Nginx 将公开路径映射到内部路径，或再增加版本别名。

### 3.1 知识库

```text
GET /api/v1/open/knowledge-bases
```

只返回当前 Token 对应用户有权访问的知识库，支持分页。禁止通过 `tenant_id` 查询其他租户数据。

### 3.2 检索

```text
POST /api/v1/open/search
```

请求体只保留：

```json
{
  "knowledge_base_id": 1001,
  "query": "员工报销需要哪些材料？",
  "mode": "vector",
  "top_k": 5
}
```

Facade 将 `knowledge_base_id` 转换为现有 Service 所需的 `kb_id`，并在调用检索前执行权限检查。

### 3.3 问答

```text
POST /api/v1/open/chat
```

客户端不得传入可信的 `user_id`。Facade 从 `CurrentUser.user_id` 注入用户身份，再调用现有 Chat Service。

### 3.4 会话

```text
GET  /api/v1/open/conversations/{conversation_id}
GET  /api/v1/open/conversations/{conversation_id}/messages
POST /api/v1/open/conversations/{conversation_id}/messages
```

读取或写入前必须校验会话归属当前用户，并校验会话绑定的知识库仍在用户访问范围内。

### 3.5 文档

第一阶段只开放读取和任务状态查询：

```text
GET /api/v1/open/documents/{document_id}
GET /api/v1/open/documents/{document_id}/tasks/{task_id}
```

文档上传可以作为第二阶段能力，仍由后端从 Token 注入创建人；文档索引触发暂不开放，避免同步任务阻塞 HTTP 请求。

## 4. 身份与权限

### 4.1 身份来源

继续使用现有：

```http
Authorization: Bearer <access_token>
```

通过现有 `auth.get_current_user` 获取：

- `user_id`
- `tenant_id`
- Token 有效期和撤销状态

开放 API 不接受以下字段作为身份依据：

- 请求体中的 `user_id`
- 表单中的 `created_by`
- 请求参数中的 `tenant_id`

### 4.2 资源权限

新增 `app/core/common/access.py`，集中提供：

```python
require_knowledge_base_access(user_id, knowledge_base_id)
require_conversation_access(user_id, conversation_id)
require_document_access(user_id, document_id)
```

权限判断复用当前知识库用户、组织和租户关系。Facade 不自行复制权限规则，避免与现有管理端规则分叉。

### 4.3 Nginx 的边界

Nginx 只做网络和流量层控制：

- 限制来源 IP（如有需要）。
- 限制请求速率和并发连接。
- 限制上传请求大小。
- 统一代理超时。
- 添加或透传 `X-Request-ID`。
- 只暴露 `/api/v1/open/`，不暴露内部管理接口。

Nginx 不判断 `kb_id`、租户、用户或资源归属。

## 5. 统一响应

开放 API 成功响应尽量复用现有业务数据结构，减少前端和 Service 改造。

错误响应统一为：

```json
{
  "request_id": "req_01HXYZ",
  "code": "KNOWLEDGE_BASE_FORBIDDEN",
  "message": "当前用户无权访问该知识库",
  "retryable": false
}
```

最少覆盖以下错误：

| HTTP 状态 | code | 场景 |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | Token 缺失、过期或已撤销 |
| 403 | `RESOURCE_FORBIDDEN` | 无权访问知识库、会话或文档 |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在 |
| 422 | `VALIDATION_ERROR` | 参数校验失败 |
| 429 | `RATE_LIMITED` | Nginx 限流 |
| 500 | `INTERNAL_ERROR` | 未处理的服务异常 |

不在普通日志中记录 Token、密码、完整文件内容和完整问题内容。

## 6. Nginx 配置职责示例

```nginx
location /api/v1/open/ {
    limit_req zone=open_api burst=20 nodelay;

    client_max_body_size 20m;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://knowledge_base_backend;
}

location /api/v1/platform/ {
    allow 10.0.0.0/8;
    deny all;
    proxy_pass http://knowledge_base_backend;
}
```

具体 upstream、网段、限流值和 CORS 来源必须根据部署环境配置，不能直接照搬示例值。

## 7. 实施顺序

### 第一阶段：只读和问答

1. 新增 Open API 路由和请求 Schema。
2. 复用现有 Token 认证。
3. 实现知识库、检索、问答接口。
4. 增加知识库资源访问检查。
5. 统一开放 API 错误响应和 request_id。
6. 增加 Nginx `/api/v1/open/` 代理和限流。

### 第二阶段：会话和文档读取

1. 增加会话归属校验。
2. 增加文档归属和知识库范围校验。
3. 开放文档详情、任务状态和会话消息。
4. 补充接口文档和权限说明。

### 第三阶段：有限文档写入

1. 增加文档上传 Facade。
2. 从 Token 注入 `created_by`。
3. 使用 Nginx 和后端双重限制文件大小。
4. 完成上传幂等和任务状态查询后，再评估是否开放索引触发。

## 8. 验收标准

- 现有管理端 API 行为不变。
- Open API 不接受客户端提交的用户和租户身份字段。
- 修改 `knowledge_base_id` 不能访问未授权知识库。
- 修改会话 ID 或文档 ID 不能读取其他用户资源。
- Open API 经 Nginx 统一限流、超时和请求体大小控制。
- Token、密码、文件内容和完整问题内容不进入普通日志。
- Open API 错误包含统一 `request_id`、错误码和可重试标记。
- 当前方案不新增应用授权表，不引入 OAuth2，不影响现有登录流程。

## 9. 后续扩展

如果未来必须支持真正的外部第三方开发者，再在 Nginx 和 Open API Facade 之间增加应用凭证解析层：

```text
应用 Token → 映射到平台用户或服务账号 → 复用 access.py 权限校验
```

这样可以保留本方案的路由、参数和 Service 调用方式，只替换身份来源，不需要重新设计业务接口。
