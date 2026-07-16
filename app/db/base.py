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

from typing import Any

from contextvars import ContextVar

from databases import Database, DatabaseURL

from app.config import CONF

DATABASE = None
DB: ContextVar = ContextVar("app_db")

async def setup():
    db_url = DatabaseURL(CONF.default.database_url)

    global DATABASE
    if db_url.scheme == "mysql":
        DATABASE = Database(
            db_url,
            minsize=50,
            maxsize=100,
            echo=CONF.default.debug,
            charset="utf8",
            client_flag=0,
        )
    elif db_url.scheme in {"sqlite", "sqlite+aiosqlite"}:
        DATABASE = Database(db_url)
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


class PageRecord():
    rows:Any=None
    total:int=0
    page: int = None
    page_size: int = None
