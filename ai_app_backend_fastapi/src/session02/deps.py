"""依存性注入で差し込む部品。テストでは app.dependency_overrides で差し替える。"""

from __future__ import annotations

from typing import Annotated

import httpx2
from fastapi import Depends, Request

from kondate.clock import Clock, SystemClock
from kondate.settings import Settings, get_settings
from src.session02.store import DataStore


def get_store(request: Request) -> DataStore:
    return request.app.state.store  # lifespan で用意したもの


def get_clock() -> Clock:
    return SystemClock()


def get_http(request: Request) -> httpx2.AsyncClient:
    return request.app.state.http  # lifespan で用意した共有クライアント


StoreDep = Annotated[DataStore, Depends(get_store)]
ClockDep = Annotated[Clock, Depends(get_clock)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
HttpDep = Annotated[httpx2.AsyncClient, Depends(get_http)]
