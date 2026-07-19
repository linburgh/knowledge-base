from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import authentication as authentication_service
from app.schemas.auth import AuthContextResponse, LoginRequest, RefreshRequest, TokenResponse

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


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


@router.get("/me", response_model=AuthContextResponse)
async def me(current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await authentication_service.me(current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest) -> Any:
    try:
        return await authentication_service.refresh(payload.refresh_token)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/logout")
async def logout(current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await authentication_service.logout(current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
