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

from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any

from databases import Database, DatabaseURL

from app.config import CONF
from app.core.common.log import LOG

DATABASE = None
DB: ContextVar = ContextVar("app_db")


def _sql_text(query: Any) -> str:
    return str(query).replace("\n", " ").strip()


def _parameter_keys(values: Any) -> list[str]:
    if not isinstance(values, dict):
        return []
    return sorted(str(key) for key in values)


class LoggingDatabase(Database):
    """Database client that records every SQL operation without logging values."""

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

    async def fetch_all(self, query: Any, values: dict | None = None):
        operation = "fetch_all"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await super().fetch_all(query, values)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            raise
        self._log_success(operation, started, result)
        return result

    async def fetch_one(self, query: Any, values: dict | None = None):
        operation = "fetch_one"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await super().fetch_one(query, values)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            raise
        self._log_success(operation, started, result, "row=1" if result is not None else "row=0")
        return result

    async def fetch_val(self, query: Any, values: dict | None = None, column: Any = 0):
        operation = "fetch_val"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await super().fetch_val(query, values, column)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            raise
        self._log_success(operation, started, result, "value_returned")
        return result

    async def execute(self, query: Any, values: dict | None = None):
        operation = "execute"
        self._log_start(operation, query, values)
        started = monotonic()
        try:
            result = await super().execute(query, values)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            raise
        self._log_success(operation, started, result, "completed")
        return result

    async def execute_many(self, query: Any, values: list):
        operation = "execute_many"
        self._log_start(operation, query, {"batch_size": len(values)})
        started = monotonic()
        try:
            result = await super().execute_many(query, values)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "DB SQL failed operation={} elapsed_ms={}",
                operation,
                int((monotonic() - started) * 1000),
            )
            raise
        self._log_success(operation, started, result, "completed")
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


@dataclass(slots=True)
class PageRecord:
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
