# Copyright 2021 99cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any, TypeVar

import sqlalchemy as sa
from databases import Database, DatabaseURL

from app.config import CONF
from app.core.common.log import LOG

DATABASE = None
DB: ContextVar = ContextVar("app_db")
T = TypeVar("T")


def _sql_text(query: Any) -> str:
    return str(query).replace("\n", " ").strip()


def _parameter_keys(values: Any) -> list[str]:
    if not isinstance(values, dict):
        return []
    return sorted(str(key) for key in values)


def _query_summary(operation: str, query: Any) -> str:
    sql = _sql_text(query)
    tables = re.findall(
        r"\b(?:from|into|update|join)\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
        sql,
        flags=re.IGNORECASE,
    )
    names = ",".join(dict.fromkeys(tables[:4])) or "unknown"
    return f"{operation}:{names}"[:256]


class LoggingDatabase(Database):
    """Database client that records every SQL operation without logging values."""

    def connection(self):
        if self._discard_released_task_connection():
            LOG.warning("DB discarded released task connection before acquire")
        return super().connection()

    def _discard_released_task_connection(self) -> bool:
        """清理由取消打断 release 后遗留在当前任务中的失效连接。"""
        connection = self._connection
        if connection is None or getattr(connection, "_connection_counter", 0) != 0:
            return False
        backend_connection = getattr(connection, "_connection", None)
        if backend_connection is None or getattr(backend_connection, "_connection", None) is None:
            return False
        self._connection = None
        return True

    async def _run_with_connection_recovery(
        self,
        operation: str,
        call: Callable[[], Awaitable[T]],
    ) -> T:
        try:
            return await call()
        except asyncio.CancelledError:
            if self._discard_released_task_connection():
                LOG.warning("DB discarded released task connection operation={}", operation)
            raise
        except AssertionError as exc:
            if str(exc) != "Connection is already acquired":
                raise
            if not self._discard_released_task_connection():
                raise
            LOG.warning("DB recovered released task connection operation={}", operation)
            return await call()

    def _log_start(self, operation: str, query: Any, values: Any) -> None:
        LOG.info(
            "DB SQL start operation={} sql={} parameter_keys={}",
            operation,
            _sql_text(query),
            _parameter_keys(values),
        )

    def _log_success(
        self,
        operation: str,
        started: float,
        result: Any,
        result_summary: str | None = None,
    ) -> None:
        if isinstance(result, list):
            summary = f"rows={len(result)}"
        elif result_summary is not None:
            summary = result_summary
        elif result is None:
            summary = "result=None"
        else:
            summary = "result_returned"
        LOG.info(
            "DB SQL success operation={} {} elapsed_ms={}",
            operation,
            summary,
            int((monotonic() - started) * 1000),
        )

    async def _monitor_operation(
        self,
        operation: str,
        query: Any,
        started: float,
        *,
        row_count: int | None = None,
        error: Exception | None = None,
    ) -> None:
        try:
            from app.core.monitoring import emit_gather_event, monitoring_emit_in_progress

            if monitoring_emit_in_progress():
                return
            summary = _query_summary(operation, query)
            if any(
                table in summary
                for table in (
                    "t_monitor_alert",
                    "t_monitor_event",
                    "t_monitor_metric_value",
                    "t_monitor_state_snapshot",
                )
            ):
                return
            duration_ms = int((monotonic() - started) * 1000)
            await emit_gather_event(
                "db.execute",
                "db_operation_failed" if error is not None else "db_operation_completed",
                operation=operation,
                query_summary=summary,
                row_count=row_count,
                slow=duration_ms >= 500,
                duration_ms=duration_ms,
                error=error,
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB monitor adapter failed operation={}",
                operation,
            )

    async def fetch_all(self, query: Any, values: dict | None = None):
        operation = "fetch_all"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await self._run_with_connection_recovery(
                operation,
                lambda: super(LoggingDatabase, self).fetch_all(query, values),
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            await self._monitor_operation(
                operation,
                query,
                started,
                error=exc,
            )
            raise
        self._log_success(operation, started, result)
        await self._monitor_operation(
            operation,
            query,
            started,
            row_count=len(result),
        )
        return result

    async def fetch_one(self, query: Any, values: dict | None = None):
        operation = "fetch_one"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await self._run_with_connection_recovery(
                operation,
                lambda: super(LoggingDatabase, self).fetch_one(query, values),
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            await self._monitor_operation(
                operation,
                query,
                started,
                error=exc,
            )
            raise
        self._log_success(operation, started, result, "row=1" if result is not None else "row=0")
        await self._monitor_operation(
            operation,
            query,
            started,
            row_count=1 if result is not None else 0,
        )
        return result

    async def fetch_val(self, query: Any, values: dict | None = None, column: Any = 0):
        operation = "fetch_val"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await self._run_with_connection_recovery(
                operation,
                lambda: super(LoggingDatabase, self).fetch_val(query, values, column),
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            await self._monitor_operation(
                operation,
                query,
                started,
                error=exc,
            )
            raise
        self._log_success(operation, started, result, "value_returned")
        await self._monitor_operation(operation, query, started)
        return result

    async def execute(self, query: Any, values: dict | None = None):
        operation = "execute"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await self._run_with_connection_recovery(
                operation,
                lambda: super(LoggingDatabase, self).execute(query, values),
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            await self._monitor_operation(
                operation,
                query,
                started,
                error=exc,
            )
            raise
        self._log_success(operation, started, result, "completed")
        await self._monitor_operation(operation, query, started)
        return result

    async def execute_many(self, query: Any, values: list):
        operation = "execute_many"
        self._log_start(operation, query, {"batch_size": len(values)})
        started = monotonic()
        try:
            result = await self._run_with_connection_recovery(
                operation,
                lambda: super(LoggingDatabase, self).execute_many(query, values),
            )
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            await self._monitor_operation(
                operation,
                query,
                started,
                error=exc,
            )
            raise
        self._log_success(operation, started, result, "completed")
        await self._monitor_operation(
            operation,
            query,
            started,
            row_count=len(values),
        )
        return result


async def setup():
    db_url = DatabaseURL(CONF.default.database_url)

    global DATABASE
    if db_url.scheme == "mysql":
        DATABASE = LoggingDatabase(
            db_url,
            minsize=50,
            maxsize=100,
            echo=CONF.default.debug,
            charset="utf8",
            client_flag=0,
        )
    elif db_url.scheme in {"sqlite", "sqlite+aiosqlite"}:
        DATABASE = LoggingDatabase(db_url)
    elif db_url.scheme in {"postgresql", "postgresql+asyncpg"}:
        DATABASE = LoggingDatabase(db_url)
    else:
        raise ValueError("Unsupported database backend")
    await DATABASE.connect()


async def inject_db():
    global DATABASE
    DB.set(DATABASE)


def get_db_name() -> str:
    """Return database name parsed from app.yaml `default.database_url`."""
    db_url = DatabaseURL(CONF.default.database_url)
    db_name = db_url.database
    if not db_name:
        raise ValueError("Database name is missing in default.database_url")
    return db_name


def database_pool_stats(db: Database | None = None) -> dict[str, int]:
    """Return live asyncpg pool usage without opening an extra connection."""
    database = db or DB.get()
    backend = getattr(database, "_backend", None)
    pool = getattr(backend, "_pool", None)
    required = ("get_size", "get_idle_size", "get_max_size")
    if pool is None or not all(callable(getattr(pool, name, None)) for name in required):
        raise RuntimeError("database pool capacity is unavailable")
    size = int(pool.get_size())
    idle = int(pool.get_idle_size())
    maximum = int(pool.get_max_size())
    return {
        "used": max(0, size - idle),
        "size": size,
        "idle": idle,
        "capacity": maximum,
    }


async def database_instance_stats(db: Database | None = None) -> dict[str, int]:
    """Return PostgreSQL instance connection usage and current-process pool details."""
    database = db or DB.get()
    db_url = DatabaseURL(CONF.default.database_url)
    if db_url.scheme not in {"postgresql", "postgresql+asyncpg"}:
        raise RuntimeError("database instance connection capacity is only available for PostgreSQL")
    row = await database.fetch_one(
        sa.text(
            """
            select
                count(*)::bigint as used,
                count(*) filter (where datname = current_database())::bigint
                    as current_database_connections,
                count(*) filter (where state = 'active')::bigint as active_connections,
                count(*) filter (where state = 'idle')::bigint as idle_connections,
                current_setting('max_connections')::integer as capacity,
                current_setting('superuser_reserved_connections')::integer
                    as reserved_connections
            from pg_stat_activity
            """
        )
    )
    if row is None:
        raise RuntimeError("database instance connection capacity is unavailable")
    pool = database_pool_stats(database)
    return {
        "used": int(row["used"]),
        "capacity": int(row["capacity"]),
        "current_database_connections": int(row["current_database_connections"]),
        "active_connections": int(row["active_connections"]),
        "idle_connections": int(row["idle_connections"]),
        "reserved_connections": int(row["reserved_connections"]),
        "pool_used": pool["used"],
        "pool_size": pool["size"],
        "pool_idle": pool["idle"],
        "pool_capacity": pool["capacity"],
    }


@dataclass(slots=True)
class PageRecord:
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
