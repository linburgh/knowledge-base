import json
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.common.exception import BusiException
from app.core.common.log import LOG

CHINA_STANDARD_TIMEZONE = ZoneInfo("Asia/Shanghai")


def utc_now() -> datetime:
    """返回带时区的 UTC 时间；业务自然日和客户展示必须先显式转换时区。"""
    return datetime.now(UTC)


def to_china_standard_time(value: datetime) -> datetime:
    """将带时区时间转换为中国标准时间，禁止猜测无时区时间的来源。"""
    if value.tzinfo is None:
        raise ValueError("Timezone-aware datetime is required")
    return value.astimezone(CHINA_STANDARD_TIMEZONE)


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


def normalize_optional_filter(value: str | None) -> str | None:
    """Treat empty query-string filters as omitted filters."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


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
    LOG.warning("business exception status={} message={}", exc.status_code, exc.message)
    raise HTTPException(status_code=exc.status_code, detail=exc.message)
