# 文档索引 Worker 说明

> 完整的需求背景、架构、任务状态、调度方案、生产化设计和验收标准见[文档索引 Worker 详细设计文档](文档索引Worker详细设计文档.md)。本文保留用于快速了解当前实现。

## 1. Worker 解决什么问题

文档上传成功，并不代表文档已经可以被问答检索。上传后还需要完成：

```text
原始文件 → 从 MinIO 下载 → 文件解析 → 文本切分 → Embedding → 保存向量 → ready
```

这些步骤可能需要几秒、几分钟甚至更长时间，不能放在上传 HTTP 请求中同步执行。因此系统使用 Worker 在后台执行文档索引任务。

## 1.1 文档索引到底是什么

文档索引不是简单记录文件名，也不是只把原始文件保存起来，而是把原始文档加工成问答系统可以查找的知识数据：

```text
原始文件 → 提取正文 → 清洗和分块 → 生成 Embedding → 保存文本与向量 → 可被检索
```

其中，文本分块是为了让系统能够定位文档中的具体知识片段；Embedding 是把片段转换成用于语义相似度计算的向量。用户提问时，问答系统会在这些已索引的片段中查找相关内容，再生成回答并返回引用。

所以，“文件已上传”和“文档已完成索引”是两个不同状态：前者表示原始资料已保存，后者才表示该文档已经具备参与问答检索的条件。Worker 负责的就是从已上传状态推动到可检索状态，并在失败时保留明确的原因和可恢复的任务记录。

## 2. Worker 是什么

Worker 可以理解为一个“后台任务执行者”。它不负责接收浏览器请求，也不负责页面展示，而是不断从数据库中查找待执行任务，然后调用业务 Service 完成任务。

当前项目的 Worker 入口是：

```text
workers/indexing.py
```

当前版本是“应用进程内 Worker”：FastAPI 启动时创建一个后台协程，由同一个 Uvicorn 进程运行；任务状态保存在 PostgreSQL 的 `t_indexing_task` 表中。

```text
FastAPI 启动
    ↓
创建 document-indexing-worker 协程
    ↓
查询 PostgreSQL 中的 pending 任务
    ↓
调用 app.core.services.ingestion.run_task()
    ↓
解析、切分、Embedding、写入向量
```

Worker 不是 Embedding 模型，也不是 Rerank 服务。Embedding 是 Worker 执行过程中的一个步骤，Worker 负责的是任务调度、状态管理和失败收敛。

## 3. 为什么不能只使用 asyncio.create_task

旧实现是在上传接口中直接创建临时协程：

```python
asyncio.create_task(ingestion_service.run_task(task_id))
```

这种方式有几个问题：

1. 协程只存在于当前 Python 进程内。
2. 服务重启后，协程会消失。
3. 数据库中的任务可能保持 `running`，文档保持 `processing`。
4. 没有统一的轮询、超时、重试和恢复机制。

现在上传接口只负责保存文件、创建文档记录和创建 `pending` 索引任务，然后立即返回；真正的索引工作由 Worker 处理。

## 4. 任务生命周期

索引任务保存在 `t_indexing_task` 表中，主要字段包括：

| 字段 | 含义 |
|---|---|
| `id` | 索引任务 ID |
| `document_id` | 对应文档 ID |
| `kb_id` | 对应知识库 ID |
| `status` | 任务状态：`pending`、`running`、`succeeded`、`failed`、`interrupted` |
| `attempts` | 已执行次数 |
| `max_attempts` | 最大执行次数，默认 3 |
| `error_message` | 最后一次失败原因 |
| `started_at` | 本次开始时间 |
| `finished_at` | 完成或失败时间 |
| `updated_at` | 最近更新时间，用于判断任务是否失联 |

正常流程：

```text
pending → running → succeeded
```

失败流程：

## 5. API 查询与重建

文档列表的“构建进度”调用 GET /api/v1/documents/{document_id}/index-progress?page=1&page_size=10，返回文档摘要、当前任务和按创建时间倒序分页的历史任务。任务记录包含状态、进度、当前阶段、时间、耗时、重试次数、版本号和失败原因。接口先校验当前用户对文档所属知识库的访问权限，禁止跨知识库读取任务。

“重建索引”调用 POST /api/v1/documents/{document_id}/index。Service 在创建任务前校验文档权限，并复用索引任务幂等规则；已有 pending 或 running 任务时不重复创建。

“中断”调用 POST /api/v1/documents/{document_id}/index-tasks/{task_id}/interrupt，请求体携带进度查询返回的 `expected_version`，仅接受 `pending` 或 `running` 任务；用户主动中断后进入 `canceled`，服务端失联恢复场景进入 `interrupted`。后端使用任务 ID、状态和版本号做条件更新，版本不一致时返回 409，不覆盖新状态。

“重试”调用 POST /api/v1/documents/{document_id}/index-tasks/{task_id}/retry，请求体同样携带 `expected_version`，仅接受 `interrupted`、`canceled` 任务。`failed` 任务当前继续使用重建索引入口。事务内校验权限、任务归属、版本号和重复任务后创建新的 `pending` 任务，并通过 `retry_of_task_id` 关联原任务。原任务保留为历史记录，不直接覆盖状态或进度。

```text
running → failed
```

中断与重试流程：

```text
running → interrupted → pending → running → succeeded
                              └→ failed
```

文档状态通常对应为：

```text
pending → processing → ready
                       └→ failed
```

任务因 Worker 失联或进程重启进入 `interrupted` 时，文档进入可重试状态；重试创建新任务后文档回到 `processing`。原中断任务不覆盖、不删除，作为历史任务保留。

只有索引任务成功写入分块和向量后，文档才会进入 `ready`，检索层也只会查询 `ready` 文档的分块。

## 5. 当前代码调用链

### 5.1 上传文档

入口：

```text
app/api/v1/documents.py
POST /api/v1/documents/upload
```

调用方向：

```text
API
  → app.core.services.document.upload()
  → 上传文件到 MinIO
  → 写入 t_document
  → app.core.services.ingestion.create_task()
  → 写入 t_indexing_task(status=pending)
  → 返回文档记录
```

上传接口不会等待 Embedding 完成。

### 5.2 Worker 轮询

`workers/indexing.py` 的主要函数：

- `run_forever()`：持续运行 Worker 主循环。
- `run_pending_once()`：恢复失联任务，并获取一个 `pending` 任务执行。

默认每 2 秒轮询一次。当前实现每轮取一个任务，避免同一个应用进程同时处理过多文档。

### 5.3 执行索引

`app/core/services/ingestion.py` 中的 `run_task()` 负责：

1. 将任务改为 `running`。
2. 增加 `attempts`。
3. 将当前文档改为 `processing`。
4. 使用总超时包裹索引过程。
5. 成功时调用 `mark_ready()`。
6. 异常或超时时调用 `mark_failed()`。

具体处理链路是：

```text
MinIO 下载
  → loaders.load_document()
  → splitters.split_documents()
  → embeddings.embed_chunks()
  → save_chunks()
  → mark_ready()
```

## 6. Embedding 为什么需要并发控制

假设一个文件切分成 2,119 个分块，每批处理 10 个分块：

```text
2119 ÷ 10 ≈ 212 次 Embedding 请求
```

如果所有请求串行执行，本地模型响应较慢时，整体耗时会非常长。当前配置如下：

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `embedding.batch_size` | 10 | 每次请求处理的分块数量 |
| `embedding.concurrency` | 4 | 最大并发请求数 |
| `embedding.retry_count` | 2 | 单批失败后的重试次数 |
| `embedding.timeout_seconds` | 120 | 单次模型请求超时 |

并发不是越大越好。并发过高可能导致模型内存不足、服务限流或请求排队，因此系统使用 `Semaphore` 限制并发数量。

## 7. 超时和失联恢复

### 7.1 任务总超时

默认索引任务最大执行时间为 1,800 秒：

```yaml
default:
  indexing_task_timeout_seconds: 1800
```

超过总时长后，任务和文档都会进入 `failed`，并记录“索引任务超过最大执行时间”。

### 7.2 任务更新时间

Embedding 每完成一批，Worker 会更新任务的 `updated_at`，这个字段相当于轻量级心跳。

默认 300 秒没有更新时间时，任务会被视为失联：

```yaml
default:
  indexing_stale_after_seconds: 300
```

下次 Worker 轮询时：

- 未达到最大重试次数：标记为 `interrupted`，由用户通过“重试”重新创建任务。
- 已达到最大重试次数：改为 `failed`。

因此服务重启后，旧的 `running` 任务不会永久卡住。

## 8. 如何启动和观察 Worker

启动后端时，Worker 会自动启动：

```bash
OS_CONFIG_DIR=$PWD/etc uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 28003
```

查看文档状态：

```bash
curl http://127.0.0.1:28003/api/v1/documents/{document_id}
```

查看日志：

```bash
tail -f log/app.log
```

重点检查：

1. Embedding 服务是否可访问。
2. Embedding 模型名称是否正确。
3. 任务的 `updated_at` 是否持续更新。
4. 是否已经超过失联阈值或任务总超时。
5. `error_message` 是否记录了解析或向量化失败原因。

## 9. 当前实现的边界

当前实现是“数据库持久化任务 + 单个应用进程内轮询 Worker”，已经解决了单实例服务重启后任务永久卡住的问题。

它还不是完整的分布式任务队列。多实例部署时，还需要增加：

- 数据库行锁或租约，避免多个实例重复领取任务。
- Redis/Arq 等外部任务队列。
- Worker 数量、并发度和数据库连接池的统一配置。
- 任务取消、死信队列和管理员手动重试。
- 更细粒度的 `processed_chunks / total_chunks` 进度字段。

因此当前实现适合开发和单实例部署验证；生产多实例部署前，应将索引 Worker 独立成可横向扩展的任务服务。

## 10. 推荐学习顺序

1. [app/api/v1/documents.py](../app/api/v1/documents.py)：上传和手动索引接口。
2. [app/core/services/document.py](../app/core/services/document.py)：文件保存和任务创建。
3. [app/core/services/ingestion.py](../app/core/services/ingestion.py)：任务状态和索引流程。
4. [workers/indexing.py](../workers/indexing.py)：Worker 轮询和恢复。
5. [app/rag/loaders.py](../app/rag/loaders.py)：文件解析。
6. [app/rag/splitters.py](../app/rag/splitters.py)：文本切分。
7. [app/rag/embeddings.py](../app/rag/embeddings.py)：批量、并发和重试。
8. [文档分块上传实现说明.md](文档分块上传实现说明.md)：完整文档接入流程。
