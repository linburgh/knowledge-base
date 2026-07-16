from dataclasses import dataclass

from fastapi import Header

from app.config import CONF
from app.core.common.exception import BusiException


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    token: str | None = None


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise BusiException("认证 Token 不能为空", status_code=401)
        return CurrentUser(user_id="token-user", token=token)

    if CONF.default.environment == "development" and CONF.default.dev_user_id:
        return CurrentUser(user_id=CONF.default.dev_user_id)

    raise BusiException("未认证", status_code=401)
