from __future__ import annotations

import asyncio


async def run_once() -> int:
    """采集入口；目标来自系统发布配置，业务页面不提供采集任务编辑。"""
    return 0


async def run_forever(stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
    while not stop_event.is_set():
        await run_once()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
