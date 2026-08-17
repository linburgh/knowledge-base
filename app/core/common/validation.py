"""Shared validation for user-entered text.

The frontend provides immediate feedback, but these checks remain authoritative
on the service boundary so API callers cannot bypass them.
"""

from __future__ import annotations

import re

from app.core.common.exception import BusiException

INVISIBLE_CHARACTER_PATTERN = re.compile(
    r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2060\u2066-\u2069\uFEFF]",
    re.UNICODE,
)
PATH_CHARACTER_PATTERN = re.compile(r'[\\/:*?"<>|]', re.UNICODE)
IDENTIFIER_PATTERN = re.compile(r"[\w.-]+", re.UNICODE)
MAINLAND_MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


def validate_text(
    value: str | None,
    field: str,
    *,
    max_length: int | None = None,
    required: bool = False,
    forbid_path: bool = False,
) -> None:
    if value is None:
        if required:
            raise BusiException(f"{field} 不能为空")
        return
    if not isinstance(value, str):
        raise BusiException(f"{field} 必须是文本")
    if required and not value.strip():
        raise BusiException(f"{field} 不能为空")
    if max_length is not None and len(value) > max_length:
        raise BusiException(f"{field} 不能超过 {max_length} 个字符")
    if INVISIBLE_CHARACTER_PATTERN.search(value):
        raise BusiException(f"{field} 不能包含控制字符或不可见字符")
    if forbid_path and (PATH_CHARACTER_PATTERN.search(value) or ".." in value):
        raise BusiException(f"{field} 不能包含路径字符")


def validate_identifier(
    value: str | None,
    field: str,
    *,
    max_length: int | None = None,
    required: bool = False,
    forbid_path: bool = False,
) -> None:
    validate_text(
        value,
        field,
        max_length=max_length,
        required=required,
        forbid_path=forbid_path,
    )
    if value is not None and value.strip() and not IDENTIFIER_PATTERN.fullmatch(value):
        raise BusiException(f"{field} 只能包含中文、字母、数字、点、下划线和短横线")


def validate_free_text(
    value: str | None,
    field: str,
    *,
    max_length: int | None = None,
    required: bool = False,
) -> None:
    validate_text(value, field, max_length=max_length, required=required)


def validate_mainland_mobile(value: str | None, field: str = "phone") -> None:
    validate_text(value, field, max_length=11)
    if value is not None and value and not MAINLAND_MOBILE_PATTERN.fullmatch(value):
        raise BusiException(f"{field} 必须是 11 位中国大陆手机号")
