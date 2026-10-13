"""画像とレシートの入口：POST /api/uploads・/api/fridge/scan・/api/receipts/import。

- uploads … セッション13（台帳に持ち主と期限 24時間）
- fridge/scan … セッション4の応答（needs_review・issues）＋セッション14の応答キャッシュ
- receipts/import … セッション7。取り込んだレシートは台帳（30日）に載せ、二重取り込みも台帳で調べる
最終で足したこと：写真・レシートから読み取った食材名（辞書の語だけ）を台帳に残し、声の相談に添える（pantry.py）。
"""

from __future__ import annotations

import hashlib
import logging

import anthropic
import anyio
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse
from ulid import ULID

from kondate.settings import get_settings
from src.final.cache import cache_key, sha256_hex
from src.final.intake import (JPEG_QUALITY, MSG_IMAGE_TOO_LARGE, MSG_TOO_LARGE, Rejected, accept_image,
                              accept_receipt, inspect_upload, save_upload)
from src.final.models import FRIDGE_SCHEMA
from src.final.pantry import FridgeNote, names_from_receipt, names_from_scan
from src.final.pdftext import parse_receipt_text
from src.final.privacy import PersonalStore
from src.final.receipts import StoredReceipt, read_receipt, review
from src.final.review import find_issues
from src.final.scan import FRIDGE_PROMPT, scan_fridge
from src.final.web import Llm, UserId, error, record_llm, tokens2, total

settings = get_settings()
log = logging.getLogger(__name__)
router = APIRouter()

PREPROCESS = {"max_long_edge": settings.image_max_long_edge, "jpeg_quality": JPEG_QUALITY}
ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0}
MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_SCAN_UPSTREAM = "画像の読み取りに失敗しました。時間をおいて試してください"
MSG_RECEIPT_UPSTREAM = "レシートの読み取りに失敗しました。時間をおいて試してください"
MSG_DUPLICATE = "このレシートはすでに取り込み済みです"


# ---------------------------------------------------------------- アップロード（セッション2・13）

@router.post("/api/uploads")
async def create_upload(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        kind, ext = await anyio.to_thread.run_sync(inspect_upload, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    upload_id = f"up_{ULID()}"
    path = await anyio.to_thread.run_sync(save_upload, request.app.state.upload_dir, upload_id, ext, raw)
    request.app.state.data.add("upload", upload_id, x_user_id, path=path)
    digest = hashlib.sha256(raw).hexdigest()
    # file.filename はログにも出さない（名前や住所が入っていることがある）
    log.info("upload_saved", extra={"fields": {"user_id": x_user_id, "upload_id": upload_id, "kind": kind,
                                               "bytes": len(raw), "sha12": digest[:12]}})
    return JSONResponse({"upload_id": upload_id, "kind": kind, "bytes": len(raw), "sha256": digest},
                        status_code=201)


# ---------------------------------------------------------------- 冷蔵庫の写真（セッション4・14）

def remember_fridge(store: PersonalStore, user_id: str, value: dict) -> None:
    """最終：要確認の印が無い食材名を、台帳に種別 upload（24時間）で残す。写真そのものは残さない。"""
    names = names_from_scan(value)
    if names:
        store.add("upload", f"up_{ULID()}", user_id, data=FridgeNote(names))


@router.post("/api/fridge/scan")
async def fridge_scan(request: Request, image: UploadFile, llm: Llm, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await image.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_IMAGE_TOO_LARGE)
    s = request.app.state
    key = cache_key(scope=x_user_id, kind="fridge_scan", content_sha256=sha256_hex(raw), preprocess=PREPROCESS,
                    prompt=FRIDGE_PROMPT, system=None, model=settings.llm_model, schema=FRIDGE_SCHEMA)
    if (hit := s.cache.get(key)) is not None:
        s.usage.count_lookup(x_user_id, hit=True)
        remember_fridge(s.data, x_user_id, hit.value)
        return JSONResponse({**hit.value, "usage": ZERO_USAGE}, headers={"x-cache": "hit"})
    s.usage.count_lookup(x_user_id, hit=False)

    try:
        prepared = await anyio.to_thread.run_sync(accept_image, raw, PREPROCESS["max_long_edge"], JPEG_QUALITY)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    used = []
    try:
        scan = await scan_fridge(llm, prepared.data, used)
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", MSG_SCAN_UPSTREAM)
    finally:
        record_llm(request, x_user_id, used)
    if scan is None:
        return error(request, 502, "invalid_output", MSG_INVALID_OUTPUT)  # 失敗はキャッシュしない

    issues = find_issues(scan.ingredients)
    value = {
        "ingredients": [i.model_dump() for i in scan.ingredients],
        "needs_review": bool(issues),
        "issues": issues,
        "image": prepared.info(),
    }
    s.cache.put(key, x_user_id, value, total(used))
    remember_fridge(s.data, x_user_id, value)
    return JSONResponse({**value, "usage": tokens2(total(used))}, headers={"x-cache": "miss"})


# ---------------------------------------------------------------- レシート（セッション7）

def find_receipt(store: PersonalStore, user_id: str, sha256: str) -> StoredReceipt | None:
    return next((h.data for h in store.live(user_id, "receipt") if h.data.sha256 == sha256), None)


@router.post("/api/receipts/import")
async def import_receipt(request: Request, file: UploadFile, llm: Llm, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    s = request.app.state
    sha256 = hashlib.sha256(raw).hexdigest()
    if find_receipt(s.data, x_user_id, sha256) is not None:
        return error(request, 409, "duplicate", MSG_DUPLICATE)  # LLM を呼ぶ前に断る
    try:
        accepted = await anyio.to_thread.run_sync(accept_receipt, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    used = []
    try:
        read = await read_receipt(llm, accepted.kind, accepted.data, used)
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", MSG_RECEIPT_UPSTREAM)
    finally:
        record_llm(request, x_user_id, used)
    if read is None:
        return error(request, 502, "invalid_output", MSG_INVALID_OUTPUT)

    text = parse_receipt_text(accepted.pdf_text)
    receipt = StoredReceipt(
        f"rcp_{ULID()}", x_user_id, sha256, accepted.kind, read,
        review(read, text, s.clock.now().date()), text is not None, names_from_receipt(read),
    )
    if find_receipt(s.data, x_user_id, sha256) is not None:   # 読み取っている間に同じレシートが取り込まれた
        return error(request, 409, "duplicate", MSG_DUPLICATE)
    s.data.add("receipt", receipt.receipt_id, x_user_id, data=receipt)
    log.info("receipt_saved", extra={"fields": {"user_id": x_user_id, "receipt_id": receipt.receipt_id,
                                                "source": receipt.source, "bytes": len(raw)}})
    return JSONResponse({**receipt.view(), "usage": tokens2(total(used))}, status_code=201)
