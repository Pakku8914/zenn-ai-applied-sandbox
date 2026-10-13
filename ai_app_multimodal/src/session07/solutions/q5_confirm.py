"""問題5：利用者が直した値を受け取り、もう一度検査してから「確認済み」にする（POST /api/receipts/{id}/confirm）。

- 直した値も人の入力なので、取り込みのときと同じ検査（整合性検査＋PDF の文字との突き合わせ）を通す
- 残った問題は、利用者が「承知のうえ」と明示した種類（acknowledged）だけ見逃す。invalid_date は見逃せない
- 問題が残っていれば保存せず status: needs_review と issues を返す（取り込みのときと同じ形で画面に出せる）

    docker compose exec api python -m src.session07.solutions.q5_confirm
"""

from __future__ import annotations

import asyncio
import json

import httpx2
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field

from kondate.clock import FixedClock
from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.media import media_path
from src.session07.app import ReceiptStore, UserId, app, error, review
from src.session07.models import ReceiptRead

MSG_NOT_FOUND = "レシートが見つかりません"
ACKNOWLEDGEABLE = {"total_mismatch", "price_out_of_range", "text_mismatch"}  # 日付は人が見れば直せるので含めない


class ConfirmIn(ReceiptRead):
    acknowledged: list[str] = Field(default_factory=list, description="承知のうえで残す問題の種類（reason）")


@app.post("/api/receipts/{receipt_id}/confirm")
async def confirm_receipt(request: Request, receipt_id: str, body: ConfirmIn, x_user_id: UserId = "u001") -> JSONResponse:
    stored = request.app.state.receipts.get(x_user_id, receipt_id)
    if stored is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    if not set(body.acknowledged) <= ACKNOWLEDGEABLE:
        return error(request, 422, "invalid_request", "入力値が正しくありません：acknowledged")
    read = ReceiptRead.model_validate(body.model_dump(exclude={"acknowledged"}))
    issues = review(read, stored.text, request.app.state.clock.now().date())
    remaining = [i for i in issues if i["reason"] not in body.acknowledged]
    if remaining:
        return JSONResponse({"receipt_id": receipt_id, "status": "needs_review", "issues": remaining})
    stored.read, stored.issues, stored.confirmed = read, issues, True
    return JSONResponse({"receipt_id": receipt_id, "status": "confirmed",
                         "acknowledged": sorted({i["reason"] for i in issues})})


# ---------------------------------------------------------------- 動作確認

GOOD = {
    "store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072,
    "items": [{"name": "鶏むね肉", "quantity": 1, "price": 398}, {"name": "キャベツ", "quantity": 1, "price": 198},
              {"name": "卵（10個入り）", "quantity": 1, "price": 248}, {"name": "牛乳", "quantity": 1, "price": 228}],
}


def variant(total: int, cabbage: int = 198) -> dict:
    d = json.loads(json.dumps(GOOD))
    d["items"][1]["price"] = cabbage
    d["total"] = total
    return d


async def run_cases() -> list:
    app.state.receipts = ReceiptStore()
    app.state.clock = FixedClock()
    app.state.llm = FakeProvider([
        ChatResult(json.dumps(variant(1063, cabbage=189), ensure_ascii=False), [], "end_turn", Usage(1652, 104)),
        ChatResult(json.dumps(variant(1000), ensure_ascii=False), [], "end_turn", Usage(778, 104)),
    ])
    out = []
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        async def confirm(rid: str, body: dict, user: str = "u001") -> tuple:
            r = await c.post(f"/api/receipts/{rid}/confirm", json=body, headers={"x-user-id": user})
            j = r.json()
            if "error" in j:
                return (r.status_code, j["error"]["type"])
            return (r.status_code, j["status"], [i["reason"] for i in j.get("issues", [])], j.get("acknowledged"))

        pdf = media_path("receipt.pdf").read_bytes()
        png = media_path("receipt.png").read_bytes()
        a = (await c.post("/api/receipts/import", files={"file": ("r.pdf", pdf, "application/pdf")})).json()
        out.append(("A 取り込み", [i["reason"] for i in a["issues"]]))
        out.append(("A キャベツを198円・合計1072円に直す", await confirm(a["receipt_id"], GOOD)))
        b = (await c.post("/api/receipts/import", files={"file": ("r.png", png, "image/png")})).json()
        out.append(("B 取り込み", [i["reason"] for i in b["issues"]]))
        out.append(("B 直さずに確定", await confirm(b["receipt_id"], variant(1000))))
        out.append(("B 合計の不一致を承知で確定", await confirm(b["receipt_id"], {**variant(1000), "acknowledged": ["total_mismatch"]})))
        out.append(("B 日付の問題を承知にしようとする", await confirm(b["receipt_id"], {**GOOD, "acknowledged": ["invalid_date"]})))
        out.append(("B 別の利用者", await confirm(b["receipt_id"], GOOD, user="u002")))
    return out


if __name__ == "__main__":
    for row in asyncio.run(run_cases()):
        print(*row)
    # A 取り込み ['text_mismatch', 'text_mismatch']
    # A キャベツを198円・合計1072円に直す (200, 'confirmed', [], [])
    # B 取り込み ['total_mismatch']
    # B 直さずに確定 (200, 'needs_review', ['total_mismatch'], None)
    # B 合計の不一致を承知で確定 (200, 'confirmed', [], ['total_mismatch'])
    # B 日付の問題を承知にしようとする (422, 'invalid_request')
    # B 別の利用者 (404, 'not_found')
