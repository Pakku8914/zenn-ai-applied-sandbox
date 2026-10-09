"""練習問題1：GET /api/users/{user_id}（公開してよい項目だけを返す）。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel

from src.session02.deps import StoreDep
from src.session02.errors import ApiError, ErrorResponse

router = APIRouter(tags=["users"])


class UserPublic(BaseModel):
    id: str
    name: str
    plan: Literal["free", "pro"]
    household_size: int


@router.get("/api/users/{user_id}", response_model=UserPublic, responses={404: {"model": ErrorResponse}})
async def get_user(user_id: Annotated[str, Path(pattern=r"^u\d{3}$")], store: StoreDep) -> dict:
    user = store.get_user(user_id)
    if user is None:
        raise ApiError(404, "not_found", f"ユーザーが見つかりません：{user_id}")
    return user  # allergies・preferences・created_at は response_model で落ちる
