# AGENTS.md

## 项目定位

本项目是基于 FastAPI 与 LangChain 的企业知识库问答系统后端脚手架。

当前阶段只保留工程骨架，不落地具体 API、Service、DB、RAG、Worker 业务实现。

## 目录边界

- `app/api/v1/`：HTTP 接口层，只负责请求解析、认证上下文、调用 Service 和响应转换。
- `app/core/services/`：业务编排层，负责校验、事务边界和调用 DB、RAG、外部服务。
- `app/db/`：数据访问层，负责连接、表结构、Repository 和向量库适配。
- `app/rag/`：LangChain 能力封装层，负责 Loader、Splitter、Embedding、Retriever 和 Chain。
- `app/schemas/`：请求、响应、分页和内部协议模型。
- `app/core/common/`：认证、异常、日志和纯工具函数。
- `workers/`：异步任务入口。
- `scripts/db/`：统一维护 DDL。
- `etc/`：配置样例和部署配置。

## 开发约定

- 遵守调用方向：`API -> Service -> DB / RAG / 外部服务`。
- 项目使用 `uv` 管理 Python、虚拟环境、依赖和锁文件。
- 新增依赖使用 `uv add`，不要手工编辑 `uv.lock`。
- `pyproject.toml` 是依赖声明源，`requirements.txt` 仅作为兼容导出文件。
- API 层不得直接访问数据库、向量库或 LLM。
- Service 层不得依赖 FastAPI 的 `Request`、`Response` 或 `HTTPException`。
- DB 层不得拼接 Prompt、生成自然语言答案或处理 HTTP 展示文案。
- RAG 层不得决定用户权限，权限过滤应在业务检索流程中前置处理。
- 新增通用逻辑前先检查 `app/core/common/`、`app/db/api.py` 等已有公用方法，优先复用，避免重复实现。
- DDL 只维护在 `scripts/db/data_table_ddl.sql`。
- 密码、Token、API Key 和本机绝对路径不得提交到仓库。

## 后续落地顺序

1. 配置系统与启动入口。
2. 健康检查与统一异常。
3. 数据库连接和基础 DDL。
4. 知识库、文档、问答 Schema。
5. 文档入库 Service。
6. Loader、Splitter、Embedding、Retriever。
7. Chat Chain 与引用返回。
8. Worker、评测和部署。
