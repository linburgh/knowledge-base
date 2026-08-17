from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.common.exception import BusiException

_WINDOW_SECONDS = 60.0
_MAX_REQUESTS = 60
_REQUESTS: dict[str, deque[float]] = defaultdict(deque)


async def rate_limit(request: Request) -> None:
    key = request.headers.get("Authorization", request.client.host if request.client else "anonymous")
    now = time.monotonic()
    bucket = _REQUESTS[key]
    while bucket and now - bucket[0] >= _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MAX_REQUESTS:
        raise BusiException("开放 API 请求过于频繁", status_code=429)
    bucket.append(now)


__all__ = ("rate_limit",)
