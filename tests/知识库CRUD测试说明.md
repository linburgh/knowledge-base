# 知识库 CRUD 测试说明

## 1. 脚本位置

```text
tests/test_knowledge_base_crud.sh
```

该脚本用于通过 HTTP 接口测试知识库的新增、列表、分页、查询、修改和删除。

默认接口地址：

```text
http://127.0.0.1:28003/api/v1
```

## 2. 前置条件

先启动后端服务：

```bash
cd /home/linburgh/workspace/ai-llm/knowledge-base
OS_CONFIG_DIR=$PWD/etc .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 28003 --reload
```

确认健康检查可用：

```bash
curl http://127.0.0.1:28003/api/v1/health
```

数据库表结构需要已经初始化：

```bash
docker compose exec -T postgres \
  psql -U linburgh -d knowledge_base \
  < scripts/db/data_table_ddl.sql
```

## 3. 一键测试完整流程

执行：

```bash
cd /home/linburgh/workspace/ai-llm/knowledge-base
tests/test_knowledge_base_crud.sh all
```

脚本默认使用 `TENANT_ID=3`，并支持通过 `AUTH_TOKEN` 传入登录令牌；新增知识库的 `owner_id` 应使用数据库中的账号（例如 `linburgh`），服务端会解析为数字 `created_by`。

`all` 会依次执行：

1. 新增知识库。
2. 查询知识库列表。
3. 查询知识库分页列表。
4. 按 ID 查询知识库详情。
5. 修改知识库。
6. 删除知识库。

脚本会输出每个接口的 JSON 响应。

## 4. 单独测试每个接口

### 4.1 新增知识库

```bash
tests/test_knowledge_base_crud.sh add
```

输出中会包含：

```text
add passed, KB_ID=1
```

后续 `get`、`modify`、`remove` 可以使用这个 `KB_ID`。

### 4.2 查询知识库列表

```bash
tests/test_knowledge_base_crud.sh list
```

请求接口：

```text
GET /api/v1/knowledge-bases?owner_id=test-user
```

该接口不分页，直接返回数组。

### 4.3 查询知识库分页列表

```bash
tests/test_knowledge_base_crud.sh page
```

指定分页参数：

```bash
PAGE=1 PAGE_SIZE=10 tests/test_knowledge_base_crud.sh page
```

请求接口：

```text
GET /api/v1/knowledge-bases/page?owner_id=test-user&page=1&page_size=10
```

脚本会校验分页响应字段：

```json
{
  "rows": [],
  "total": 0,
  "page": 1,
  "page_size": 10
}
```

### 4.4 按 ID 查询知识库

```bash
KB_ID=1 tests/test_knowledge_base_crud.sh get
```

请求接口：

```text
GET /api/v1/knowledge-bases/1
```

### 4.5 修改知识库

```bash
KB_ID=1 tests/test_knowledge_base_crud.sh modify
```

请求接口：

```text
PUT /api/v1/knowledge-bases/1
```

脚本内置修改入参，包括：

- `name`
- `owner_id`
- `description`
- `visibility`
- `embedding_model`
- `chunk_size`
- `chunk_overlap`
- `retrieval_top_k`

### 4.6 删除知识库

```bash
KB_ID=1 tests/test_knowledge_base_crud.sh remove
```

也可以使用：

```bash
KB_ID=1 tests/test_knowledge_base_crud.sh delete
```

请求接口：

```text
DELETE /api/v1/knowledge-bases/1
```

当前删除是软删除，脚本会校验返回值中的：

```json
{
  "status": "deleted"
}
```

## 5. 常用环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BASE_URL` | API 基础地址 | `http://127.0.0.1:28003/api/v1` |
| `OWNER_ID` | 请求中的 owner_id | `test-user` |
| `NAME_PREFIX` | 测试知识库名称前缀 | `kb-shell-test` |
| `KB_ID` | 知识库 ID，`get/modify/remove` 必填 | 空 |
| `PAGE` | 分页页码 | `1` |
| `PAGE_SIZE` | 每页条数 | `20` |
| `CURL_CONNECT_TIMEOUT` | curl 连接超时时间 | `5` |
| `CURL_MAX_TIME` | curl 单请求最大时间 | `30` |

## 6. 示例

完整测试：

```bash
tests/test_knowledge_base_crud.sh all
```

先新增，再查询：

```bash
tests/test_knowledge_base_crud.sh add
KB_ID=1 tests/test_knowledge_base_crud.sh get
```

分页查询：

```bash
PAGE=1 PAGE_SIZE=5 tests/test_knowledge_base_crud.sh page
```

指定其他服务地址：

```bash
BASE_URL=http://127.0.0.1:8000/api/v1 tests/test_knowledge_base_crud.sh all
```

## 7. 常见问题

### 7.1 curl 连接失败

如果出现：

```text
curl: (7) Couldn't connect to server
```

说明后端服务没有启动，或端口不可达。先确认：

```bash
curl http://127.0.0.1:28003/api/v1/health
```

### 7.2 分页接口返回 500

先确认服务已经重新加载最新代码。使用 `--reload` 启动时通常会自动重载；如果没有，手动重启 uvicorn。

### 7.3 get/modify/remove 提示 KB_ID 缺失

这些动作需要指定知识库 ID：

```bash
KB_ID=1 tests/test_knowledge_base_crud.sh get
```
