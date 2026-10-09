"""要求の本文から ChatRequest を作る依存性。

予算の判定（budget.enforce_budget）はこの ChatDep を受け取って見積もるので、本文の形が違うアプリ（final の UIMessage[]）は
build_chat だけを自分の形に差し替えればよい。モデルは必ず ChatRequest.model に入れる（単価表を引くキーになる）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from kondate.settings import get_settings

from .providers import ChatRequest


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


def get_model(request: Request) -> str:
    """いま上流に送るモデル（lifespan で設定から決めた値）。"""
    return request.app.state.model


ModelDep = Annotated[str, Depends(get_model)]


async def build_chat(body: ChatIn, model: ModelDep) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": body.message}],
                       max_tokens=get_settings().llm_max_tokens, model=model)


ChatDep = Annotated[ChatRequest, Depends(build_chat)]
