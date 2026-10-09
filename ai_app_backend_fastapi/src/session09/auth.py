"""認証の依存性。Authorization: Bearer <API キー> を確かめ、いまの利用者（CurrentUser）を返す。

ルートは CurrentUserDep を受け取るだけでよい。失敗はすべて同じ 401 unauthorized（WWW-Authenticate: Bearer 付き）。
ログに残すのは失敗の理由と先頭8文字だけで、キーそのものは決して書かない。
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

logger = logging.getLogger("kondate.session09.auth")

# auto_error=False：ヘッダが無いときに FastAPI 既定の例外を投げさせず、自分で共通エラー本文を返す
bearer = HTTPBearer(auto_error=False, description="API キー（kd_ で始まる文字列）")


def get_clock() -> Clock:
    """時計の依存性。テストでは dependency_overrides で FixedClock に差し替える。"""
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock)]


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", {"WWW-Authenticate": "Bearer"})


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: SessionDep,
    clock: ClockDep,
) -> CurrentUser:
    request_id = request.state.request_id
    if credentials is None:  # ヘッダが無い・Bearer 以外の方式・値が空
        logger.info("auth_failed reason=no_bearer request_id=%s", request_id)
        raise unauthorized()
    result = await keys.authenticate(session, credentials.credentials, now=clock.now())
    if result.user is None:
        logger.info("auth_failed reason=%s key_prefix=%s request_id=%s",
                    result.reason, result.prefix or "-", request_id)
        raise unauthorized()
    return result.user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
