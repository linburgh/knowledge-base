# PostgreSQL 16 容器化部署文档

## 1. 目标

本文说明如何使用 Docker / Docker Compose 部署知识库项目依赖的 PostgreSQL 16 数据库，并启用 pgvector 扩展。

适用范围：

- 本地开发环境。
- 测试环境。
- 单节点 MVP 部署。

生产环境可以继续使用本文的镜像和初始化方式，但应补充备份、监控、权限隔离、磁盘规划和高可用方案。

## 2. 技术基线

| 项 | 选择 |
|---|---|
| PostgreSQL | 16 |
| 向量扩展 | pgvector |
| 容器镜像 | `pgvector/pgvector:pg16` |
| 默认端口 | `5432` |
| 数据目录 | Docker volume |
| DDL 脚本 | `scripts/db/data_table_ddl.sql` |

## 3. 目录建议

```text
project-root/
├── docker-compose.yml
├── scripts/
│   └── db/
│       └── data_table_ddl.sql
└── docs/
    └── PostgreSQL16容器化部署.md
```

数据库数据不应写入项目源码目录，应使用 Docker volume 或独立挂载盘。

## 4. Docker Compose 配置

项目根目录的 `docker-compose.yml` 中保留 PostgreSQL 服务：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: knowledge_base
      POSTGRES_USER: linburgh
      POSTGRES_PASSWORD: linburgh
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U linburgh -d knowledge_base"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

说明：

- `POSTGRES_DB`：启动时自动创建的数据库。
- `POSTGRES_USER`：应用连接用户。
- `POSTGRES_PASSWORD`：本地可用简单密码，生产必须改为强密码并通过环境变量或密钥系统注入。
- `postgres_data`：持久化数据库数据。
- `healthcheck`：用于 Compose 或部署平台判断数据库是否可用。

## 5. 本地启动

在项目根目录执行：

```bash
docker compose up -d postgres
```

查看状态：

```bash
docker compose ps postgres
```

查看日志：

```bash
docker compose logs -f postgres
```

停止服务：

```bash
docker compose stop postgres
```

停止并删除容器，但保留数据卷：

```bash
docker compose down
```

删除数据卷会清空数据库，谨慎执行：

```bash
docker compose down -v
```

## 6. 连接数据库

进入容器：

```bash
docker compose exec postgres psql -U linburgh -d knowledge_base
```

宿主机连接串：

```text
postgresql://linburgh:linburgh@127.0.0.1:5432/knowledge_base
```

应用配置示例：

```yaml
default:
  database_url: postgresql://linburgh:linburgh@127.0.0.1:5432/knowledge_base
```

如果使用 `databases` + `asyncpg`，也可以配置：

```yaml
default:
  database_url: postgresql+asyncpg://linburgh:linburgh@127.0.0.1:5432/knowledge_base
```

## 7. 初始化扩展和表结构

DDL 已集中维护在：

```text
scripts/db/data_table_ddl.sql
```

执行 DDL：

```bash
docker compose exec -T postgres \
  psql -U linburgh -d knowledge_base \
  < scripts/db/data_table_ddl.sql
```

DDL 中包含：

```sql
create extension if not exists vector;
```

因此执行脚本后会自动启用 pgvector 扩展。

验证扩展：

```bash
docker compose exec postgres \
  psql -U linburgh -d knowledge_base \
  -c "select extname, extversion from pg_extension where extname = 'vector';"
```

验证表：

```bash
docker compose exec postgres \
  psql -U linburgh -d knowledge_base \
  -c "\dt t_*"
```

## 8. 重新初始化数据库

仅本地开发或测试环境可使用。

```bash
docker compose down -v
docker compose up -d postgres
docker compose exec -T postgres \
  psql -U linburgh -d knowledge_base \
  < scripts/db/data_table_ddl.sql
```

生产环境不得使用 `down -v` 清理数据。

## 9. 备份和恢复

### 9.1 备份

```bash
mkdir -p backups

docker compose exec -T postgres \
  pg_dump -U linburgh -d knowledge_base \
  --format=custom \
  > backups/knowledge_base_$(date +%Y%m%d%H%M%S).dump
```

### 9.2 恢复

```bash
docker compose exec -T postgres \
  pg_restore -U linburgh -d knowledge_base \
  --clean \
  --if-exists \
  < backups/knowledge_base_xxx.dump
```

恢复前应确认目标库可被覆盖。

## 10. 生产配置建议

生产环境至少调整以下项：

- 使用强密码，不提交到 Git。
- 不直接暴露 `5432` 到公网。
- 将数据库数据卷挂载到可靠磁盘。
- 配置定时备份和恢复演练。
- 配置磁盘、水位、连接数、慢 SQL 监控。
- 按 Worker 数量和连接池大小评估 `max_connections`。
- 不使用 `latest` 镜像标签。
- 数据库升级前先在测试环境验证 DDL、pgvector 和应用兼容性。

## 11. 常见问题

### 11.1 端口被占用

检查本机是否已有 PostgreSQL：

```bash
ss -ltnp | grep 5432
```

如果端口冲突，可以修改 Compose 端口映射：

```yaml
ports:
  - "15432:5432"
```

应用连接串同步改为：

```text
postgresql://linburgh:linburgh@127.0.0.1:15432/knowledge_base
```

### 11.2 pgvector 扩展不存在

确认镜像为：

```text
pgvector/pgvector:pg16
```

然后重新执行：

```bash
docker compose exec postgres \
  psql -U linburgh -d knowledge_base \
  -c "create extension if not exists vector;"
```

### 11.3 数据库连接失败

检查：

- 容器是否运行。
- `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB` 是否与应用配置一致。
- 端口映射是否正确。
- 应用是否使用了错误的代理环境变量。

命令：

```bash
docker compose ps postgres
docker compose logs postgres
docker compose exec postgres pg_isready -U linburgh -d knowledge_base
```
