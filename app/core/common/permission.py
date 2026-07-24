from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar, cast

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def require_action(action_code: str, *, user_parameter: str = "current_user"):
    """Require a fixed action before entering a Service method."""

    if not action_code or not action_code.strip():
        raise ValueError("action_code cannot be empty")

    def decorator(function: F) -> F:
        signature = inspect.signature(function)

        @wraps(function)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind_partial(*args, **kwargs)
            current_user = bound.arguments.get(user_parameter)
            if not isinstance(current_user, CurrentUser):
                raise BusiException("缺少权限上下文", status_code=401)

            from app.core.services import permission as permission_service

            await permission_service.require_action(current_user, action_code)
            return await function(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


__all__ = ("require_action",)
