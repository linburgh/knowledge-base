from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from databases import Database, DatabaseURL

from app.config import CONF


DATABASE: Database | None = None
DB: ContextVar[Database | None] = ContextVar("app_db", default=None)


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return

    path = urlparse(database_url).path
    if not path or path == ":memory:":
        return

    if path.startswith("//"):
        db_path = Path("/" + path.lstrip("/"))
    else:
        db_path = Path(path.lstrip("/"))
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


async def setup() -> None:
    db_url = DatabaseURL(CONF.default.database_url)
    scheme = db_url.scheme

    global DATABASE
    _ensure_sqlite_parent(CONF.default.database_url)

    if scheme.startswith("sqlite"):
        DATABASE = Database(db_url)
    elif scheme in {"postgresql", "postgresql+asyncpg", "postgres"}:
        DATABASE = Database(db_url)
    elif scheme in {"mysql", "mysql+aiomysql"}:
        DATABASE = Database(
            db_url,
            minsize=5,
            maxsize=20,
            echo=CONF.default.debug,
            charset="utf8",
        )
    else:
        raise ValueError(f"Unsupported database backend: {scheme}")

    if CONF.default.db_connect_on_startup and not DATABASE.is_connected:
        await DATABASE.connect()


async def shutdown() -> None:
    global DATABASE
    if DATABASE is not None and DATABASE.is_connected:
        await DATABASE.disconnect()


async def inject_db() -> None:
    if DATABASE is None:
        await setup()
    DB.set(DATABASE)


def get_database() -> Database | None:
    return DATABASE


def get_db_name() -> str:
    db_url = DatabaseURL(CONF.default.database_url)
    db_name = db_url.database
    if not db_name:
        raise ValueError("Database name is missing in default.database_url")
    return db_name


class PageRecord:
    rows: Any = None
    total: int = 0
    page: int | None = None
    page_size: int | None = None
