"""自分のデータ：DELETE /api/me/data（セッション13）と GET /api/usage（セッション14）。

DELETE は、台帳（アップロード・冷蔵庫の食材名・文書・レシート・保存した音声）と利用記録に加えて、
最終で次の2つも消す。応答の形（deleted の5つのキー）はセッション13のまま変えない。
- 応答キャッシュのその利用者の分（ResponseCache.forget。残すと、消したはずの写真の読み取り結果が返ってくる）
- 取り込みジョブ（止めて結果を捨て、以後は 404。ジョブの結果には PDF から読んだレシピが入っている）
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, Request

from src.final.api_documents import forget_jobs
from src.final.web import USER_ID_PATTERN, UserId

log = logging.getLogger(__name__)
router = APIRouter()


@router.delete("/api/me/data")
async def delete_my_data(request: Request,
                         x_user_id: Annotated[str, Header(alias="x-user-id", pattern=USER_ID_PATTERN)]) -> dict:
    """x-user-id は必須（消す操作に「既定の利用者」を使わない）。2回目は 0 件を返す。"""
    s = request.app.state
    await forget_jobs(s, x_user_id)                 # 先に止める（取り消しの途中で利用量が書き足されるため）
    deleted = s.data.delete_user(x_user_id)
    deleted["usage"] = s.usage.forget(x_user_id)
    s.cache.forget(x_user_id)
    log.info("data_deleted", extra={"fields": {"user_id": x_user_id, **deleted}})
    return {"deleted": deleted}


@router.get("/api/usage")
async def usage(request: Request, x_user_id: UserId = "u001") -> dict:
    return request.app.state.usage.summary(x_user_id)
