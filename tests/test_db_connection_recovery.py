from __future__ import annotations

import asyncio

import pytest

from app.db.base import LoggingDatabase


class _BackendConnection:
    def __init__(self, acquired: bool = True) -> None:
        self._connection = object() if acquired else None


class _CachedConnection:
    def __init__(self, *, counter: int, acquired: bool = True) -> None:
        self._connection_counter = counter
        self._connection = _BackendConnection(acquired)


@pytest.mark.asyncio
async def test_connection_discards_released_proxy_left_by_cancelled_release():
    database = LoggingDatabase("postgresql://user:password@localhost/test")
    stale = _CachedConnection(counter=0)
    database._connection = stale

    connection = database.connection()

    assert connection is not stale
    assert database._connection is connection


@pytest.mark.asyncio
async def test_connection_does_not_discard_active_transaction_connection():
    database = LoggingDatabase("postgresql://user:password@localhost/test")
    active = _CachedConnection(counter=1)
    database._connection = active

    connection = database.connection()

    assert connection is active


@pytest.mark.asyncio
async def test_connection_assertion_recovers_once_after_stale_connection_cleanup():
    database = LoggingDatabase("postgresql://user:password@localhost/test")
    database._connection = _CachedConnection(counter=0)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AssertionError("Connection is already acquired")
        return "recovered"

    result = await database._run_with_connection_recovery("fetch_all", operation)

    assert result == "recovered"
    assert calls == 2
    assert database._connection is None


@pytest.mark.asyncio
async def test_cancelled_operation_discards_stale_connection_before_propagating_cancel():
    database = LoggingDatabase("postgresql://user:password@localhost/test")
    database._connection = _CachedConnection(counter=0)

    async def operation():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await database._run_with_connection_recovery("fetch_all", operation)

    assert database._connection is None
