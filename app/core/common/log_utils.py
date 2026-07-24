from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, cast

from app.core.common.log import LOG


def trace[F: Callable[..., Any]](func: F) -> F:
    """记录函数抛出的异常，并保持原异常继续向上抛出。

    该装饰器不记录函数参数，避免把密码、Token 或其他敏感业务数据写入日志。
    同步和异步函数均可使用：

    .. code-block:: python

        @trace
        async def create(...):
            ...
    """

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                LOG.opt(exception=exc).error(
                    "Service function failed: {}",
                    func.__qualname__,
                )
                raise

        return cast(F, async_wrapper)

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            LOG.opt(exception=exc).error(
                "Service function failed: {}",
                func.__qualname__,
            )
            raise

    return cast(F, wrapper)


__all__ = ("trace",)
