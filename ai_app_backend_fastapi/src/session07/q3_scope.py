"""練習問題3の解答：1リクエスト1セッション。途中で例外が起きたら、何も残らない。"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import repo
from .deps import SessionDep
from .errors import install_error_handling

app = FastAPI(title="練習問題3：セッションの寿命")
install_error_handling(app)


class TurnIn(BaseModel):
    user_id: str = Field(pattern=r"^u\d{3}$")
    fail: bool = False  # True なら、保存の途中でわざと例外を起こす


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/q3/turns", status_code=201)
async def create_turn(body: TurnIn, session: SessionDep) -> dict:
    conv = await repo.create_conversation(session, user_id=body.user_id, title="練習問題3")
    await repo.append_turn(session, conv.id, user_content="こんにちは",
                           assistant_content=[{"type": "text", "text": "こんにちは。何を作りましょうか。"}])
    if body.fail:
        raise RuntimeError("保存の途中で失敗しました（練習用）")  # flush 済みでも commit 前なので取り消される
    await session.commit()
    return {"id": conv.id}
