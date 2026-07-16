from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar


Fn = TypeVar("Fn", bound=Callable[..., Any])


class InterfaceType(str, Enum):
    internal = "internal"
    admin = "admin"
    public = "public"


SchemaT = Dict[str, Any]
EnvT = Optional[Dict[str, str]]


__all__ = ("SchemaT", "EnvT", "Fn", "InterfaceType")
