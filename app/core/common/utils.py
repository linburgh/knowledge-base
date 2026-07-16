import json
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.common.exception import BusiException


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_request_id() -> str:
    return uuid4().hex


def mask_sensitive(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clear_field_nv(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        values = asdict(value)
    elif hasattr(value, "model_dump"):
        values = value.model_dump()
    elif isinstance(value, Mapping):
        values = dict(value)
    else:
        values = dict(vars(value))
    return {key: item for key, item in values.items() if item is not None}


def parse_dataclass(value: object, cls: type) -> Any:
    if isinstance(value, cls):
        return value
    if hasattr(value, "model_dump"):
        values = value.model_dump()
    elif is_dataclass(value):
        values = asdict(value)
    elif isinstance(value, Mapping):
        values = dict(value)
    else:
        values = dict(vars(value))
    return cls(**values)


def raise_http_exception(exc: BusiException) -> None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.message)
