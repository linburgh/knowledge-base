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
- Service 层调用 DB 时优先调用对应表模块，例如 `app/db/document.py`；已有表模块时不要直接操作 `app/db/models.py` 或通用 `app/db/api.py`。
- DB 层不得拼接 Prompt、生成自然语言答案或处理 HTTP 展示文案。
- DB 层按表封装 `insert_`、`batch_insert`、`update_`、`delete_`、`get`、`list` 等通用方法，内部复用 `app/db/api.py`；过滤条件统一使用关键字参数传入。
- DB 层不要新增 `list_by_xxx`、`list_pending`、`delete_by_xxx`、`update_by_xxx` 这类只绑定单一字段或单一状态的方法。
- RAG 层不得决定用户权限，权限过滤应在业务检索流程中前置处理。
- 新增通用逻辑前先检查 `app/core/common/`、`app/db/api.py` 等已有公用方法，优先复用，避免重复实现。
- DDL 只维护在 `scripts/db/data_table_ddl.sql`。
- DDL 中 `create index` 语句保持单行书写，例如 `create index if not exists idx_x on t_x (field);`。
- 密码、Token、API Key 和本机绝对路径不得提交到仓库。

## 方案设计约束

- 在用户没有明确要求缩小范围时，方案按完整目标设计和实现，不默认采用 MVP、最小可行版本、第一阶段裁剪或“先做简化版”的思路。
- 只有用户明确提出 MVP、分阶段交付、范围裁剪或简化实现时，才可以按这些限制设计方案。
- 方案文档应覆盖完整业务流程、页面/模块、接口、状态、异常、权限、扩展性和实施计划；不能擅自用 MVP 代替完整方案。

## 前端项目约束

- 前端项目目录为 `/home/linburgh/workspace/ai-llm/knowledge-base-web`，与本后端项目同级。
- 前端项目名称固定为 `knowledge-base-web`。
- 前端技术栈固定为 Vue 3 + TypeScript + Vite + Element Plus（Vue 3 对应的 Element UI 组件库）+ Vue Router + Pinia + Axios。
- 原型和前端页面中的所有列表必须同时提供查询条件和分页，不得只实现静态列表。
- 列表操作列统一使用文本按钮，分页的上一页、下一页、页码和每页条数控件也统一使用文本按钮或文本样式，不使用带背景色的按钮。
- 列表的查询条件、分页和操作按钮属于统一 UI 设计原则，新增列表页面时必须同步设计并实现。

## 后续落地顺序

1. 配置系统与启动入口。
2. 健康检查与统一异常。
3. 数据库连接和基础 DDL。
4. 知识库、文档、问答 Schema。
5. 文档入库 Service。
6. Loader、Splitter、Embedding、Retriever。
7. Chat Chain 与引用返回。
8. Worker、评测和部署。
