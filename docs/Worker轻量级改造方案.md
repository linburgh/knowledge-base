# Worker轻量级改造方案

## 1. 方案定位

本文档设计文档索引 Worker 的轻量级改造方案。

本方案明确采用以下方式：

```text
FastAPI 后端进程
    ├── HTTP API
    ├── Service
    └── APScheduler
          └── 周期扫描并执行索引任务
```

不再部署独立 Worker 服务，也不再维护独立 Worker 进程。APScheduler 只负责按照固定间隔触发任务处理函数，业务任务状态仍然保存到 PostgreSQL 的 `t_indexing_task` 表中。

本次方案只解决当前阶段最重要的问题：

- 将索引任务从 HTTP 请求中解耦；
- 将 Worker 纳入后端应用生命周期；
- 后端重启后能够重新处理未完成的任务；
- 保持实现简单，便于开发、测试和部署。

本方案不引入 Redis、Arq、Celery、XXL-JOB、数据库 Advisory Lock、任务租约或心跳机制。多实例、多进程下的任务并发控制使用数据库条件更新，不使用 `FOR UPDATE`。

## 2. 需求背景

### 2.1 为什么需要 Worker

文档上传成功后，还需要执行文件解析、文本切分、Embedding 和向量写入。这些步骤可能耗时较长，不能在上传 HTTP 请求中同步完成。

正确的调用关系是：

```text
用户上传文档
    ↓
API / Service 保存文档并创建索引任务
    ↓
立即返回任务信息
    ↓
APScheduler 定时触发任务处理
    ↓
索引文档并更新任务状态
```

### 2.2 当前实现问题

当前后端启动时通过 `asyncio.create_task()` 启动常驻 Worker 协程。该方式可以工作，但存在以下问题：

- Worker 启动和停止逻辑直接写在 `app/main.py` 中；
- 业务应用生命周期和 Worker 轮询逻辑耦合；
- 使用手写常驻循环，不利于统一管理调度配置；
- 后端重启后，正在执行的任务可能停留在 `running` 状态；
- 目前的 `workers/` 目录容易被误解为需要独立部署的 Worker 服务目录。

### 2.3 本次改造目标

改造后：

1. 后端启动时启动 APScheduler。
2. APScheduler 每隔固定时间扫描数据库中的待处理任务。
3. 找到任务后调用现有索引 Service 执行。
4. 后端关闭时停止 APScheduler。
5. 后端启动时将超时未更新的 `running` 任务恢复为 `pending`。
6. 任务状态、进度、失败原因和重试次数继续以数据库为准。

## 3. 方案边界

### 3.1 本次实现内容

- 新增一个后端内置的 APScheduler 调度模块。
- 注册一个文档索引周期任务。
- 删除文档索引 Worker 的常驻 `asyncio` 轮询入口。
- 保留 `app/core/services/ingestion.py` 作为索引业务执行入口。
- 保留 `t_indexing_task` 作为任务持久化表。
- 增加后端启动时的失联任务恢复。
- 使用单个后端进程运行 APScheduler。
- 补充调度器启动、任务执行、重启恢复和关闭测试。

### 3.2 明确不做的事情

本方案不实现以下内容：

- 不部署独立 Worker 服务；
- 不创建 Redis 或其他消息队列；
- 不使用 APScheduler 的一次性 Job；
- 不使用 Advisory Lock；
- 不实现任务租约、Worker 心跳和跨实例接管；
- 不实现 Embedding 批次级断点续跑；
- 不把索引任务拆分为多个子任务。

## 4. 总体架构

### 4.1 运行架构

```text
FastAPI 启动
    ↓
初始化数据库和配置
    ↓
恢复超时 running 任务为 pending
    ↓
启动 AsyncIOScheduler
    ↓
注册文档索引周期 Job
    ↓
每隔 5 秒执行一次
    ↓
通过条件更新原子领取 pending 任务
    ↓
调用 ingestion.run_claimed_task(task_id)
    ↓
更新任务和文档状态
```

### 4.2 任务来源

索引任务由 API/Service 创建，不由 APScheduler 创建：

```text
上传文档 / 点击重新索引
    ↓
document Service 校验权限
    ↓
事务内写入 t_indexing_task(status = pending)
    ↓
事务提交
    ↓
等待 APScheduler 下一次周期执行
```

任务创建成功后不需要调用调度器，也不需要在 Service 中保存 asyncio Task。即使任务创建后后端立即重启，任务仍然在数据库中，重启后的调度器会重新扫描到它。

### 4.3 任务事实来源

APScheduler 只保存进程内的调度信息，不能作为业务任务记录。以下内容全部以数据库为准：

- 任务是否存在；
- 任务当前状态；
- 任务执行进度；
- 任务重试次数；
- 任务失败原因；
- 文档是否可以进入 `ready`。

## 5. 目录规划

### 5.1 改造后的目录

```text
app/
├── worker/
│   ├── __init__.py
│   ├── indexing.py          # 文档索引 Worker、APScheduler 和索引周期任务
│   └── evaluation.py        # 自主评测 Worker 执行逻辑
├── core/
│   └── services/
│       └── ingestion.py     # 文档索引业务流程
├── db/
│   └── indexing_task.py     # 索引任务查询和更新
└── main.py                  # 启动和关闭 scheduler

（改造后不再保留 workers/ 目录）
```

### 5.2 文件职责

| 文件 | 职责 |
| --- | --- |
| `app/workers/indexing.py` | 文档索引 Worker、APScheduler 注册、启动和关闭调度器 |
| `app/core/services/ingestion.py` | 执行文档下载、解析、切分、Embedding、写入和状态收口 |
| `app/db/indexing_task.py` | 原子领取待处理任务、分页查询历史任务、更新任务状态 |
| `app/main.py` | 在 FastAPI 生命周期中调用调度器启动和关闭方法 |
| `app/workers/evaluation.py` | 从原 `workers/evaluation.py` 迁移的自主评测 Worker 代码 |
| `workers/` | 改造完成后删除整个目录 |

### 5.3 Worker 代码纳入后端模块

本次改造不是只把 Worker 的启动方式改成 APScheduler，而是将原 `workers/` 目录下的 Worker 代码整体迁移到后端的 `app/workers/` 模块中。

迁移后，文档索引 Worker 不再作为独立目录、独立入口或独立进程存在。它只是后端应用中的一个调度模块：

```text
原来的 workers/indexing.py
    ├── run_pending_once()
    └── run_forever()

迁移后的 app/workers/indexing.py
    ├── process_pending_tasks()
    ├── recover_stale_tasks()
    ├── start()
    └── stop()

原来的 workers/evaluation.py
    └── 迁移到 app/workers/evaluation.py
```

具体代码对应关系如下：

| 原代码 | 改造后 | 处理方式 |
| --- | --- | --- |
| `workers/indexing.py:run_pending_once()` | `app/workers/indexing.py:process_pending_tasks()` | 改为“原子领取任务并调用 `ingestion.run_claimed_task()`”，由 APScheduler 周期调用 |
| `workers/indexing.py:run_forever()` | 不再保留 | 删除手写 `while + sleep + stop_event` 循环，由 APScheduler 管理执行间隔 |
| `app/main.py` 创建 `asyncio.Task` | `app/main.py` 调用 `indexing_scheduler.start()` | 纳入 FastAPI 启动生命周期 |
| `app/main.py` 取消 `asyncio.Task` | `app/main.py` 调用 `indexing_scheduler.stop()` | 纳入 FastAPI 关闭生命周期 |
| `workers/evaluation.py` | `app/workers/evaluation.py` | 保留自主评测执行逻辑，只迁移模块位置和导入路径 |
| `workers/` 目录 | 无对应目录 | 确认无引用后整体删除 |

迁移后的调用方向为：

```text
app/main.py
    ↓
app/workers/indexing.py
    ↓
app/core/services/ingestion.py
    ↓
app/db/indexing_task.py
    ↓
PostgreSQL
```

其中：

- `app/main.py` 只负责应用生命周期，不执行索引业务；
- `app/workers/indexing.py` 负责文档索引 Worker、APScheduler 注册、周期触发和任务恢复；
- `app/core/services/ingestion.py` 负责完整的文档索引业务流程；
- `app/db/indexing_task.py` 负责数据库任务查询和状态更新。

`app/workers/evaluation.py` 负责自主评测任务执行逻辑。自主评测的业务逻辑本次不重写，只迁移模块位置和导入路径；原 `workers/` 目录不再保留。

## 6. 依赖和配置

### 6.1 增加依赖

使用 `uv` 增加 APScheduler 3.x：

```bash
uv add "APScheduler>=3.10,<4.0"
```

不手工编辑 `uv.lock`。依赖声明以 `pyproject.toml` 为准。

### 6.2 配置项

在 `app/config/default.py` 增加以下配置：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | ---: | --- |
| `scheduler_enabled` | bool | `true` | 是否启动后端内置调度器 |
| `indexing_stale_after_seconds` | int | `300` | `running` 任务超过该时间视为失联 |
| `indexing_scheduler_batch_size` | int | `1` | 每次最多处理的任务数量 |

扫描间隔固定为 5 秒，不单独增加调度间隔配置，避免轻量方案引入不必要的配置项。原有 `indexing_worker_poll_seconds` 改造完成后删除。

在 `etc/app.yaml.example` 中增加：

```yaml
default:
  scheduler_enabled: true
  indexing_stale_after_seconds: 300
  indexing_scheduler_batch_size: 1
```

## 7. APScheduler 代码设计

### 7.1 调度器实例

`app/workers/indexing.py` 只维护一个模块级调度器实例：

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

indexing_scheduler = AsyncIOScheduler()
```

### 7.2 周期任务

使用 APScheduler 的装饰器注册一个周期任务：

```python
indexing_scheduler = AsyncIOScheduler()


@indexing_scheduler.scheduled_job(
    "interval",
    seconds=5,
    id="document-indexing-scheduler",
    max_instances=1,
    coalesce=True,
)
async def process_pending_tasks() -> None:
    db = DB.get()
    for _ in range(CONF.default.indexing_scheduler_batch_size):
        task = await indexing_task_db.claim_pending_task(db)
        if task is None:
            return
        try:
            await ingestion.run_claimed_task(task["id"])
        except Exception:
            LOG.exception(
                "document indexing scheduled task failed task_id={}",
                task["id"],
            )


def start() -> None:
    if not CONF.default.scheduler_enabled:
        return
    indexing_scheduler.start()


def stop() -> None:
    if indexing_scheduler.running:
        indexing_scheduler.shutdown(wait=False)
```

这里的 `max_instances=1` 表示同一个 APScheduler 进程中，上一轮任务还没有结束时，不启动下一轮相同 Job，避免同一进程内产生重叠执行。

### 7.3 关键注册代码

文档索引任务由 `process_pending_tasks()` 方法执行，定时任务注册就在该方法上方的装饰器中完成：

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import CONF
from app.core.common.log import LOG
from app.core.services import ingestion
from app.db import indexing_task as indexing_task_db
from app.db.base import DB

indexing_scheduler = AsyncIOScheduler()


@indexing_scheduler.scheduled_job(
    trigger="interval",
    seconds=5,
    id="document-indexing-scheduler",
    max_instances=1,
    coalesce=True,
)
async def process_pending_tasks() -> None:
    """定时查询并执行一个批次的文档索引任务。"""
    db = DB.get()
    for _ in range(CONF.default.indexing_scheduler_batch_size):
        task = await indexing_task_db.claim_pending_task(db)
        if task is None:
            return
        try:
            await ingestion.run_claimed_task(task["id"])
        except Exception:
            LOG.exception(
                "document indexing scheduled task failed task_id={}",
                task["id"],
            )


def start() -> None:
    if CONF.default.scheduler_enabled and not indexing_scheduler.running:
        indexing_scheduler.start()


def stop() -> None:
    if indexing_scheduler.running:
        indexing_scheduler.shutdown(wait=False)
```

`max_instances=1` 只能限制同一个 APScheduler 进程内的 Job 重叠，不能解决多进程、多实例并发。因此任务是否被成功领取，必须由数据库条件更新决定，不能依赖 `asyncio.Lock`。

注册关系是：

```text
@indexing_scheduler.scheduled_job(...)
        ↓
process_pending_tasks()
        ↓ 每 5 秒由 APScheduler 自动调用
indexing_task_db.list(status="pending")
        ↓
indexing_task_db.claim_pending_task()
        ↓
ingestion.run_claimed_task(task_id)
```

`@scheduled_job` 只负责把方法注册到调度器；真正开始执行要等 `start()` 被 FastAPI 启动生命周期调用。`stop()` 在 FastAPI 关闭生命周期中调用，负责停止后续调度。

`max_instances=1` 防止同一个后端进程内上一轮任务未结束时再次启动同一个 Job；`coalesce=True` 表示后端短暂暂停后恢复时，将错过的多次触发合并为一次执行。

### 7.4 原子领取任务

`process_pending_tasks()` 不先查询任务再单独更新状态，而是调用 `claim_pending_task()` 一次完成任务领取。Repository 使用条件更新和 `RETURNING`，不显式使用 `FOR UPDATE`：

这是 PostgreSQL 的 `UPDATE ... RETURNING` 写法。`RETURNING` 不是业务特殊语法，而是让数据库在完成更新后，把成功更新的记录直接返回给程序。

```sql
with candidate as (
    select id
    from t_indexing_task
    where status = 'pending'
    order by created_at asc, id asc
    limit 1
)
update t_indexing_task as task
set status = 'running',
    attempts = task.attempts + 1,
    started_at = coalesce(task.started_at, now()),
    current_step = '解析原始文件',
    updated_at = now()
from candidate
where task.id = candidate.id
  and task.status = 'pending'
returning task.*;
```

对于已经确定任务 ID 的场景，核心条件可以简化为：

```sql
update t_indexing_task
set status = 'running'
where id = :task_id
  and status = 'pending'
returning *;
```

执行结果只有两种：

```text
返回 1 条记录：领取成功，当前进程可以执行任务
返回 0 条记录：领取失败，任务已经被其他进程领取或状态已发生变化
```

`status = 'pending'` 是领取条件，`returning *` 是领取结果。业务代码必须根据是否返回记录决定是否调用 `run_claimed_task()`，不能无论返回结果如何都继续执行。

多个进程同时执行时，即使选择到同一候选任务，最终也只有一个 `UPDATE` 能够满足 `task.status = 'pending'` 并返回任务；其他进程返回空结果，直接等待下一轮调度。

对应 Repository 方法：

```python
async def claim_pending_task(db) -> dict[str, Any] | None:
    async with db.transaction():
        return await db.fetch_one(CLAIM_PENDING_TASK_QUERY)
```

该方法只负责把任务从 `pending` 改为 `running`，不执行文档解析和 Embedding。领取事务提交后，`process_pending_tasks()` 调用 `ingestion.run_claimed_task(task["id"])` 执行已经领取的任务。需要新增该方法，避免现有 `run_task()` 看到任务已经是 `running` 后直接返回。

### 7.5 为什么只需要一个装饰器/一个 Job

APScheduler 的核心作用只是定时调用函数，复杂的业务逻辑不放在调度器里：

```text
APScheduler
    └── 定时调用 process_pending_tasks()

process_pending_tasks()
    └── 原子领取 pending 任务并调用 ingestion.run_claimed_task()

ingestion.run_claimed_task()
    └── 完成完整的文档索引业务流程
```

因此不需要为每个文档创建 APScheduler Job，也不需要把任务状态保存到 APScheduler 中。

## 8. FastAPI 生命周期改造

### 8.1 当前代码

当前 `app/main.py` 通过以下方式启动文档索引 Worker：

```python
indexing_worker_task = asyncio.create_task(
    indexing_worker.run_forever(indexing_stop_event),
    name="document-indexing-worker",
)
```

改造后删除文档索引相关的：

- `indexing_stop_event`；
- `indexing_worker_task`；
- 删除 `workers.indexing` 导入，改为 `from app.workers import indexing as indexing_worker`；
- `indexing_worker.run_forever(...)` 调用；
- `on_shutdown()` 中对文档索引协程的取消逻辑。

### 8.2 改造后的生命周期

```python
from app.workers import evaluation as evaluation_worker
from app.workers import indexing as indexing_worker


async def on_startup() -> None:
    configure("app")
    log_setup(...)
    await db_setup()
    await indexing_worker.recover_stale_tasks()
    indexing_worker.start()


async def on_shutdown() -> None:
    indexing_worker.stop()
```

自主评测 Worker 的执行逻辑迁移到 `app/workers/evaluation.py`，其现有调度逻辑本次保持不变，但由后端模块统一维护。

### 8.3 启动顺序

必须按照以下顺序启动：

```text
加载配置
    ↓
初始化日志
    ↓
连接数据库
    ↓
恢复失联索引任务
    ↓
启动 APScheduler
```

不能在数据库连接完成之前启动调度器，否则周期任务可能在数据库不可用时反复报错。

## 9. 后端重启恢复

### 9.1 恢复规则

本方案不引入租约和心跳，使用已有的 `updated_at` 判断任务是否失联：

```text
启动后查询 status = running 的任务
    ↓
updated_at 早于当前时间 - indexing_stale_after_seconds
    ↓
任务 attempts < max_attempts
    ↓
恢复为 pending
    ↓
等待 APScheduler 下一轮执行
```

如果任务已经达到最大重试次数：

```text
running + 已超过最大重试次数
    ↓
更新为 failed
    ↓
记录“索引任务失联且已超过最大重试次数”
    ↓
同步文档状态为 failed
```

### 9.2 恢复代码

建议在 `app/workers/indexing.py` 中提供：

```python
async def recover_stale_tasks() -> None:
    db = DB.get()
    stale_before = utc_now() - timedelta(
        seconds=max(1, int(CONF.default.indexing_stale_after_seconds)),
    )
    tasks = await indexing_task_db.list(db, status="running")
    for task in tasks:
        updated_at = task.get("updated_at") or task.get("started_at")
        if updated_at is None or updated_at > stale_before:
            continue
        if int(task.get("attempts") or 0) >= int(task.get("max_attempts") or 3):
            await ingestion.mark_failed(
                task["id"],
                "索引任务失联且已超过最大重试次数",
            )
            continue
        await indexing_task_db.update_(
            db,
            {
                "status": "pending",
                "current_step": "等待恢复",
                "error_message": "后端重启后恢复索引任务",
                "updated_at": utc_now(),
            },
            id=task["id"],
            status="running",
        )
```

系统恢复方法必须与用户手动取消方法分开，不能调用需要用户 `expected_version` 的取消接口。

### 9.3 恢复后的执行方式

恢复任务从头执行，不做中间断点续跑：

```text
后端重启
    ↓
running 任务恢复为 pending
    ↓
APScheduler 找到 pending 任务
    ↓
ingestion.run_claimed_task(task_id)
    ↓
重新下载、解析、切分、Embedding 和写入
```

当前索引数据在流程末尾统一写入，因此从头重试可以保持实现简单。写入前应按照现有 `document_id` 和 `index_version_id` 规则清理旧分块，避免重复数据。

### 9.4 后端服务突然中断时的半途任务处理

这是本方案必须处理的核心场景。后端可能因为进程崩溃、容器被重启、机器断电或发布终止而突然中断，无法执行正常的关闭清理逻辑。

处理原则如下：

1. 索引任务在开始执行前已经写入 `t_indexing_task`，不会因为进程中断而丢失。
2. 服务中断时，正在执行的任务通常会停留在 `running`，任务的 `progress` 和 `current_step` 保留在数据库中。
3. 后端下一次启动时，在启动 APScheduler 之前，将上一次遗留的 `running` 任务恢复为 `pending`。
4. 恢复时将进度重置为 0、阶段重置为“等待恢复”，并保留原任务的 `attempts` 记录。
5. 如果任务已经达到 `max_attempts`，则直接标记为 `failed`，不再无限重试。
6. 任务恢复后从头执行，不从中间解析步骤或 Embedding 批次继续。

启动恢复流程：

```text
后端突然中断
    ↓
半途任务记录仍为 running
    ↓
后端重新启动
    ↓
查询上一次遗留的 running 任务
    ↓
attempts 未达到上限：改为 pending
    ↓
APScheduler 下一轮领取任务
    ↓
重新解析、切分、Embedding 和写入
```

需要区分以下几种中断位置：

| 中断位置 | 重启后的处理 |
| --- | --- |
| 文件下载或解析中 | 重新下载并从解析开始执行 |
| 文本切分中 | 重新解析并重新切分 |
| Embedding 中 | 重新生成全部分块的 Embedding |
| 向量写入前 | 重新执行完整索引 |
| 向量写入事务中 | 事务回滚后重新写入 |
| 向量写入完成但任务状态未更新 | 重试前清理并替换同一文档/索引版本的分块 |
| 任务已成功提交为 `succeeded` | 不再恢复，不重复执行 |

本方案不承诺中断点续跑。这样设计是因为当前索引结果在流程末尾通过短事务统一写入，重试时可以使用“删除旧分块 + 批量写入新分块”的幂等方式收敛结果。即使服务在写入或状态更新附近中断，重启后也不会保留一组混杂的新旧索引数据。

启动恢复必须发生在 APScheduler 启动之前。恢复逻辑只能处理 `updated_at` 已超过失联阈值的任务，不能在启动时无条件重置全部 `running` 任务，否则可能把其他仍在运行的后端实例的任务错误重置。多个实例同时恢复时，状态更新也必须带 `status = 'running'` 条件。

## 10. 任务执行流程

### 10.1 创建任务

```text
API / Service
    ↓
校验文档和知识库权限
    ↓
事务内创建 t_indexing_task(status = pending)
    ↓
事务内更新 t_document(status = processing)
    ↓
提交事务并返回 task_id
```

### 10.2 APScheduler 执行任务

```text
周期 Job 原子领取 pending 任务
    ↓
调用 ingestion.run_claimed_task(task_id)
    ↓
任务已由 claim_pending_task 改为 running
    ↓
执行文档索引
    ↓
成功：任务 succeeded，文档 ready
失败：任务 failed，文档 failed
```

### 10.3 任务状态

```text
pending → running → succeeded
                   ↘ failed

后端重启：
running（超时） → pending → running
```

用户主动取消的任务继续使用现有 `canceled` 状态；取消后的任务不会被 APScheduler 重新执行，因为调度器只查询 `pending`。

## 11. 并发和部署约束

### 11.1 多进程部署

多个后端进程或实例都可以启动自己的 APScheduler。`max_instances=1` 只限制单个进程内的重复 Job，跨进程的任务唯一性由 `claim_pending_task()` 的数据库条件更新保证：

```bash
WORKERS_NUM=2 uv run gunicorn -c etc/gunicorn.conf.py app.main:app
```

每个进程都会执行 FastAPI 启动生命周期并启动 APScheduler，但多个进程不会重复执行同一任务：所有进程都必须先通过数据库条件更新领取任务，只有返回记录的进程可以调用 `run_claimed_task()`。

单进程仍然是开发环境的推荐配置，因为它更容易观察和调试；它不是任务正确性的前置条件。

### 11.2 单进程内并发

调度器 Job 配置：

- `max_instances=1`；
- `coalesce=True`；
- 每轮最多处理 1 个任务；
- 上一轮未结束时不启动下一轮；
- 索引任务内部的 Embedding 并发继续使用现有 `embedding.concurrency`。

这样可以确保轻量方案下索引任务不会无限制占用后端事件循环。

### 11.3 API 与索引任务的资源影响

由于 API 和索引任务处于同一个进程，需要限制：

- 单次索引任务最大执行时间；
- Embedding 批量大小和并发数；
- 单轮处理任务数量；
- 文件上传大小；
- 任务扫描频率。

如果后续发现索引任务影响 API 延迟，再重新评估拆分服务；当前不提前引入独立 Worker。

## 12. 代码改造清单

### 12.1 `pyproject.toml`

通过 `uv add` 增加 APScheduler 依赖，并执行锁文件更新。

### 12.2 `app/config/default.py`

增加：

- `scheduler_enabled`；
- `indexing_scheduler_batch_size`；
- 保留并复用 `indexing_stale_after_seconds`。

### 12.3 `etc/app.yaml.example`

增加后端调度器配置示例，并删除不再使用的 `indexing_worker_poll_seconds` 配置。

### 12.4 `app/workers/indexing.py`

新增以下函数：

```python
start() -> None
stop() -> None
process_pending_tasks() -> Coroutine
recover_stale_tasks() -> Coroutine
```

### 12.5 `app/main.py`

删除文档索引 Worker 的常驻协程启动和停止逻辑，改为调用调度器模块的 `start()` 和 `stop()`。

### 12.6 `app/workers/evaluation.py`

从 `workers/evaluation.py` 迁移代码并修正所有导入路径，确保自主评测任务仍可执行。

### 12.7 删除 `workers/` 目录

索引 Worker 和评测 Worker 迁移完成后，使用 `rg` 确认没有 `workers` 模块引用，再删除整个 `workers/` 目录。删除前必须完成后端导入检查和测试。

### 12.8 `app/core/services/ingestion.py`

保留现有索引业务流程，重点调整：

- 修复失联恢复调用参数问题；
- 新增独立的系统恢复方法；
- 确保恢复任务只能从 `pending` 重新执行；
- 新增 `run_claimed_task(task_id)`，执行已由 Repository 原子领取为 `running` 的任务；
- 保留 `run_task(task_id)` 作为需要自行完成状态转换的兼容入口，不能让调度器在原子领取后再次调用它；
- 保证失败状态和文档状态同步更新；
- 确认重试不会产生重复分块。

## 13. 测试方案

### 13.1 调度器测试

- `scheduler_enabled=false` 时不启动调度器。
- 调度器启动后注册一个固定 ID 的文档索引 Job。
- 重复调用 `start()` 不会注册多个相同 Job。
- 调度器关闭后不再执行新的周期任务。
- Job 执行异常只记录日志，不导致调度器退出。

### 13.2 任务执行测试

- `pending` 任务能够被周期 Job 查询到。
- 周期 Job 能够原子领取任务并调用 `ingestion.run_claimed_task()`。
- 没有待处理任务时不执行索引逻辑。
- 同一轮最多处理配置数量的任务。
- 多个进程同时领取同一任务时，只有一个进程能获得 `RETURNING` 结果。
- 领取失败的进程不会调用 `run_claimed_task()`。
- 任务成功后状态为 `succeeded`，文档状态为 `ready`。
- 任务失败后状态为 `failed`，文档状态为 `failed`。

### 13.3 重启恢复测试

- 后端重启后，未开始执行的 `pending` 任务能够继续执行。
- `running` 任务超过失联时间后能够恢复为 `pending`。
- 恢复后的任务能够重新执行完整索引流程。
- 后端在解析、Embedding、写入和状态更新等不同阶段突然中断后，重启能够恢复半途任务。
- 半途任务重试后不会产生重复或混合的新旧分块。
- 已经是 `succeeded` 的任务不会被启动恢复逻辑重新执行。
- 达到最大重试次数的任务进入 `failed`，不再无限重试。
- 用户取消的 `canceled` 任务不会被恢复为 `pending`。
- 恢复过程不会错误调用用户取消接口。

### 13.4 部署测试

- `WORKERS_NUM>=1` 时每个进程都能启动 APScheduler，多个进程不会重复执行同一任务。
- 启动、关闭和重启后数据库连接正常释放。
- 后端关闭时不会遗留无法解释的临时调度状态。
- API 请求与索引任务能够在同一进程中正常运行。

## 14. 实施步骤

1. 使用 `uv add` 增加 APScheduler 依赖。
2. 增加调度器配置。
3. 新建 `app/workers/__init__.py` 和 `app/workers/indexing.py`。
4. 在调度模块中实现一个周期 Job。
5. 在 `app/main.py` 的启动和关闭生命周期中接入调度器。
6. 增加启动时失联任务恢复。
7. 修复 `ingestion.py` 中失联恢复的状态处理。
8. 将自主评测 Worker 迁移到 `app/workers/evaluation.py` 并修正导入。
9. 确认无 `workers` 引用后删除整个 `workers/` 目录。
10. 使用单进程完成基础验证，再使用多进程验证数据库原子领取。
11. 执行调度器、任务执行、评测执行和重启恢复测试。

## 15. 部署配置

开发环境推荐启动方式：

```bash
WORKERS_NUM=1 uv run gunicorn -c etc/gunicorn.conf.py app.main:app
```

推荐配置：

```yaml
default:
  scheduler_enabled: true
  indexing_scheduler_batch_size: 1
  indexing_stale_after_seconds: 300
```

部署关系：

```text
一个 FastAPI 进程
    ├── 提供 HTTP API
    ├── 启动 APScheduler
    └── 执行文档索引任务
```

## 16. 风险说明

| 风险 | 说明 | 当前处理方式 |
| --- | --- | --- |
| 多进程重复调度 | 多个进程会各自启动 APScheduler | 由数据库条件更新保证同一任务只有一个进程领取 |
| 任务从头重试 | 不支持中间批次断点续跑 | 当前任务规模下接受该方案 |
| API 与索引共享资源 | 索引可能影响接口延迟 | 限制单任务、单轮任务数和 Embedding 并发 |
| APScheduler Job 丢失 | 进程内 Job 不持久化 | 数据库任务表保留任务，重启后重新扫描 |
| 强制退出 | 当前任务会中断 | 重启时根据 `updated_at` 恢复超时 `running` 任务 |

## 17. 验收标准

- 不再启动独立文档索引 Worker 进程。
- 后端启动时能够启动一个 APScheduler。
- APScheduler 只注册一个文档索引周期 Job。
- `pending` 任务能够被周期扫描并执行。
- 后端重启后，`pending` 任务能够继续执行。
- 后端重启后，超时的 `running` 任务能够恢复为 `pending` 并重新执行。
- 达到最大重试次数的任务能够进入 `failed`。
- 用户取消的任务不会被调度器重新执行。
- 任务成功、失败和文档状态能够保持一致。
- 使用 `WORKERS_NUM=1` 部署时，API 和索引任务均能正常运行。
- 使用多个进程或实例时，同一任务不会被重复领取。
- 调度器关闭后不会继续创建新的索引任务执行。
