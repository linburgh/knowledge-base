from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.common.exception import BusiException

VALID_RANGES = {"7d": 7, "30d": 30, "90d": 90}


def resolve_range(
    range_name: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    if range_name not in (*VALID_RANGES, "custom"):
        raise BusiException("range 必须是 7d、30d、90d 或 custom")
    if range_name == "custom":
        if start_at is None or end_at is None:
            raise BusiException("custom 范围必须提供 start_at 和 end_at")
    else:
        if start_at is not None or end_at is not None:
            raise BusiException("预设范围不需要提供 start_at 或 end_at")
        end_at = datetime.now(UTC)
        start_at = end_at - timedelta(days=VALID_RANGES[range_name])
    assert start_at is not None and end_at is not None
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise BusiException("时间参数必须包含时区")
    if start_at >= end_at:
        raise BusiException("start_at 必须早于 end_at")
    return start_at, end_at


__all__ = ("VALID_RANGES", "resolve_range")
