"""認証の依存性（session09/auth.py のコピー。ApiError の引数の順をこの章の errors.py に合わせた）。

ルートは CurrentUserDep を受け取るだけでよい。失敗はすべて同じ 401 unauthorized（WWW-Authenticate: Bearer 付き）。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kondate.clock import Clock, SystemClock

from . import keys
from .deps import SessionDep
from .errors import ApiError
from .keys import CurrentUser

logger = logging.getLogger("kondate.session10.auth")

bearer = HTTPBearer(auto_error=False, description="API キー（kd_ で始まる文字列）")


def get_clock() -> Clock:
    """時計の依存性。認証の期限もレート制限もクォータも、この1つの時計で判定する。"""
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock)]


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: SessionDep,
    clock: ClockDep,
) -> CurrentUser:
    request_id = request.state.request_id
    if credentials is None:
        logger.info("auth_failed reason=no_bearer request_id=%s", request_id)
        raise unauthorized()
    result = await keys.authenticate(session, credentials.credentials, now=clock.now())
    if result.user is None:
        logger.info("auth_failed reason=%s key_prefix=%s request_id=%s",
                    result.reason, result.prefix or "-", request_id)
        raise unauthorized()
    return result.user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
