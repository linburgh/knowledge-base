# Knowledge Base

Knowledge Base 是一个基于 FastAPI、LangChain 与 PostgreSQL/pgvector 构建的企业知识库问答系统后端，覆盖多租户管理、文档入库、向量检索、智能问答、自主评测和运行监控等能力。

项目已经形成可运行的后端服务，不再只是目录脚手架。配套前端项目为同级目录下的 `knowledge-base-web`。

## 产品演示

[![企业知识库问答系统功能演示，点击查看或下载完整 PPT](https://github.com/user-attachments/assets/ffa4651c-6f2e-4196-92b3-fa548b7f9b1c)](docs/ppt/企业知识库问答系统-客户介绍-全功能真实界面版.pptx)

动态封面展示系统介绍中的代表页面并自动循环播放。点击封面可查看或下载[完整 PPT](docs/ppt/企业知识库问答系统-客户介绍-全功能真实界面版.pptx)。

## 核心能力

- 知识库管理：知识库、文档、分块、索引版本、问答配置和权限范围管理。
- 文档入库：文件上传、内容解析、文本切分、向量化、索引构建和失败任务恢复。
- 智能问答：检索、重排、上下文组装、工具调用、结构化回答、引用整理和会话管理。
- 租户权限：平台、租户、组织、用户、角色、菜单和操作权限管理。
- 自主评测：评测任务、数据集、指标计算、结果报告和评测 Agent 调度。
- 自主监控：运行事件、指标聚合、告警通知、审计追踪和监控分析 Agent。
- 开放接入：开发者开放接口、访客问答和统一认证能力。

## 系统结构

核心调用方向如下：

```text
HTTP 请求
  -> API（请求解析、认证、响应转换）
  -> Service（业务校验、事务和流程编排）
  -> Agent / RAG / DB / 外部服务
  -> PostgreSQL、pgvector、MinIO、模型服务
```

知识问答、自主评测和自主监控分别使用独立的 Agent Harness。每个 Harness 独立维护入口、运行时、权限策略、工具注册和技能文件，避免共享私有状态或隐式调用工具。

## 技术栈

| 分类 | 主要技术 |
| --- | --- |
| Web 服务 | Python 3.12、FastAPI、Uvicorn、Gunicorn |
| Agent / RAG | LangChain、LangGraph、Deep Agents |
| 数据访问 | SQLAlchemy、databases、asyncpg |
| 数据存储 | PostgreSQL 16、pgvector、MinIO、Redis |
| 任务调度 | APScheduler、异步 Worker |
| 配置管理 | YAML、环境变量、python-dotenv、Pydantic |
| 工程工具 | uv、pytest、Ruff、Docker Compose |

## 目录说明

```text
knowledge-base/
├── app/
│   ├── agents/                 # knowledge、evaluation、monitoring Agent Harness
│   ├── api/                    # HTTP 接口和路由注册
│   ├── core/
│   │   ├── common/             # 认证、异常、日志和通用工具
│   │   └── services/           # platform、knowledge_base、monitoring 业务服务
│   ├── db/                     # 数据库基础设施与领域 Repository
│   ├── rag/                    # Loader、Splitter、Embedding、Retriever、Chain
│   ├── schemas/                # 请求、响应和内部结构化协议
│   ├── workers/                # 索引、评测和监控 Worker
│   └── main.py                 # FastAPI 应用入口
├── docs/                       # 需求、架构、实施方案和测试用例
├── etc/                        # 应用配置样例和 Gunicorn 配置
├── reranker-adapter/           # 重排模型适配服务
├── scripts/
│   └── db/                     # DDL、基础配置和默认账号脚本
├── tests/                      # 单元、集成、契约和评测测试
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## 快速开始

### 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16，并启用 pgvector 扩展
- MinIO
- Redis
- 可用的对话模型、Embedding 模型；启用重排时还需要 Reranker 服务

推荐使用 Docker Compose 启动基础设施，再在宿主机运行后端，便于开发调试。

### 安装依赖

```bash
uv python install 3.12
uv sync
```

### 准备配置

```bash
cp etc/app.yaml.example etc/app.yaml
cp .env.example .env
```

根据实际环境修改 `.env`。如果后端运行在宿主机，而 PostgreSQL 和 MinIO 运行在 Docker 中，需要将对应主机名改为 `127.0.0.1`；如果后端也运行在 Compose 网络中，则使用服务名 `postgres`、`minio` 和 `redis`。

配置加载入口为 `etc/app.yaml`，本地启动时通过 `OS_CONFIG_DIR` 指定配置目录。密码、Token、API Key 和本机绝对路径不得提交到仓库。

### 启动基础设施

Compose 使用外部网络，首次运行时先创建网络：

```bash
docker network inspect knowledge-base-net >/dev/null 2>&1 || \
  docker network create knowledge-base-net
docker compose up -d postgres redis minio
```

### 初始化数据库

数据库结构统一维护在 `scripts/db/data_table_ddl.sql`，基础配置数据维护在 `scripts/db/data_table_dml.sql`。

```bash
docker compose exec -T postgres \
  psql -U linburgh -d knowledge_base \
  < scripts/db/data_table_ddl.sql

docker compose exec -T postgres \
  psql -U linburgh -d knowledge_base \
  < scripts/db/data_table_dml.sql
```


### 启动后端

```bash
OS_CONFIG_DIR="$PWD/etc" \
  uv run uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 28003 \
  --reload
```

启动后可访问：

- 健康检查：`http://127.0.0.1:28003/api/v1/health`
- Swagger UI：`http://127.0.0.1:28003/docs`
- OpenAPI：`http://127.0.0.1:28003/openapi.json`

生产环境默认关闭 Swagger UI 和 OpenAPI 文档。

## Docker Compose 部署

完成环境变量配置和数据库初始化后，可以构建并启动后端与配套前端：

```bash
docker compose up -d --build kb_service kb_web
docker compose ps
```

默认端口如下：

| 服务 | 端口 |
| --- | --- |
| 后端 API | `28003` |
| 前端 | `8080` |
| PostgreSQL | `5432` |
| Redis | `6379` |
| MinIO API | `9000` |
| MinIO Console | `9001` |

`kb_web` 的构建上下文指向同级目录 `../knowledge-base-web`，完整 Compose 部署前请确保前端仓库已存在。

## Agent 与 Worker

### Agent Harness

- `app/agents/knowledge/`：知识库问答 Agent，负责检索工具编排、回答生成和引用返回。
- `app/agents/evaluation/`：自主评测 Agent，负责评测数据、执行流程、指标和报告。
- `app/agents/monitoring/`：自主监控 Agent，负责监控事实查询、分析和结构化结论。

工具调用必须经过对应 Agent 的显式注册、权限校验、数据范围校验和运行预算校验。租户、组织和知识库范围仍由确定性业务代码控制，不能只依赖模型 Prompt。

### 后台任务

- `app/workers/indexing.py`：索引任务恢复、调度和执行。
- `app/workers/evaluation.py`：评测任务消费和状态管理。
- `app/workers/monitoring/collect.py`：监控事件采集。
- `app/workers/monitoring/aggregate.py`：监控指标聚合。
- `app/workers/monitoring/notify.py`：监控告警通知。

应用启动时会初始化数据库连接、恢复遗留索引任务，并启动已启用的评测和监控 Worker。

## 开发与验证

### 常用命令

```bash
# 静态检查
uv run ruff check app tests

# 运行测试
uv run pytest -q

# 检查 Python 模块是否可编译
uv run python -m compileall -q app tests
```

新增依赖统一使用 `uv add`，不要手工编辑 `uv.lock`。`pyproject.toml` 是依赖声明源，`requirements.txt` 仅用于兼容导出。

### 分层约束

- API 层只处理请求、认证上下文和响应转换，不直接访问数据库、向量库或模型。
- Service 层负责业务校验、事务和流程编排，数据库写操作必须显式使用事务。
- DB 层负责数据访问和 SQL 日志，不拼接 Prompt 或生成自然语言答案。
- RAG 层负责文档处理和检索能力，不决定用户权限。
- Agent 通过公开结构化协议与 Service、工具和其他 Agent 协作。

### 数据库约束

- DDL 只维护在 `scripts/db/data_table_ddl.sql`。
- 每张表使用自增 `id` 主键，不创建数据库外键和 `CHECK` 约束。
- 表间完整性、租户边界和删除策略由 Service 与 Repository 保证。
- 修改数据库结构或配置数据后，应同步更新脚本、文档和对应测试。

## 安全说明

- 不要提交真实密码、Token、API Key、Cookie、私有证书或本机绝对路径。
- 测试账号仅用于受控开发和测试环境，不得复用到生产环境。
- 上传文件、知识库检索和 Agent 工具调用必须执行租户与组织数据范围校验。
- 生产部署应使用独立密钥、最小权限账号、受控网络和持久化存储，并关闭调试模式。
