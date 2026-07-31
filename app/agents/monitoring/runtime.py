from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitoringRuntime:
    timeout_seconds: float = 15.0
    max_context_items: int = 50

    async def run(self, operation):
        return await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
