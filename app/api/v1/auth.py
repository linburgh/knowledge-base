from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import authentication as authentication_service
from app.schemas.auth import LoginRequest

router = APIRouter()


@router.post("/login")
async def login(payload: LoginRequest, request: Request) -> Any:
    try:
        return await authentication_service.login(
            payload.account,
            payload.password,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            request_id=request.headers.get("X-Request-ID"),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
