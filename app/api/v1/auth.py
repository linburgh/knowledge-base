from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services.platform import authentication as authentication_service
from app.core.services.platform import permission as permission_service
from app.core.services.platform import system_menu as system_menu_service
from app.schemas.auth import (
    AuthContextResponse,
    LoginRequest,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionResponse,
    RefreshRequest,
    TenantSelectionRequest,
    TokenResponse,
)
from app.schemas.menu import MenuTreeResponse

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


@router.get("/menus", response_model=MenuTreeResponse)
async def menus(current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await system_menu_service.get_menus(current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/permissions", response_model=PermissionResponse)
async def permissions(current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await permission_service.get_permissions(current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/permissions/check", response_model=PermissionCheckResponse)
async def check_permissions(
    payload: PermissionCheckRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await permission_service.check_actions(current_user, payload.action_codes)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tenants")
async def tenants(current_user: auth.CurrentUser = current_user_dependency) -> Any:
    try:
        return await authentication_service.tenants(current_user)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/tenant", response_model=AuthContextResponse)
async def select_tenant(
    payload: TenantSelectionRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await authentication_service.select_tenant(current_user, payload.tenant_id)
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
