"""認証の依存性（session13/auth.py のコピー）。失敗はすべて同じ 401 unauthorized（WWW-Authenticate: Bearer 付き）。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import keys
from .deps import ClockDep, SessionDep
from .errors import ApiError
from .keys import CurrentUser

logger = logging.getLogger("kondate.final.auth")

bearer = HTTPBearer(auto_error=False, description="API キー（kd_ で始まる文字列）")


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: SessionDep,
    clock: ClockDep,
) -> CurrentUser:
    if credentials is None:
        logger.info("auth_failed", extra={"reason": "no_bearer"})
        raise unauthorized()
    result = await keys.authenticate(session, credentials.credentials, now=clock.now())
    await session.commit()  # 読み取りのトランザクションを閉じる（このあとストリーミングで長く握らない）
    if result.user is None:
        logger.info("auth_failed", extra={"reason": result.reason, "key_prefix": result.prefix})
        raise unauthorized()
    return result.user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
