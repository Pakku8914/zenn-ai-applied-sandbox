"""セッション7の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session07

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE を切り替えなくてよい）。
mockllm の付属シナリオ receipt（priority 70・「レシート」）を使う。
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
from datetime import date

import httpx2
from anthropic import AsyncAnthropic
from PIL import Image

from kondate.clock import FixedClock
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.media import EXPECTED_SHA12, media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session07.app import ReceiptStore, app
from src.session07.checks import MESSAGES, check_receipt
from src.session07.models import RECEIPT_SCHEMA, ReceiptRead
from src.session07.pdftext import extract_text, parse_receipt_text, squash
from src.session07.read import RECEIPT_PROMPT

PNG = media_path("receipt.png").read_bytes()
PDF = media_path("receipt.pdf").read_bytes()
RCP_ID = re.compile(r"^rcp_[0-9A-HJKMNP-TV-Z]{26}$")
MOCK = get_settings().mockllm_url
LIMIT = get_settings().upload_max_bytes
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"

GOOD = {
    "store": "こんだてマート",
    "purchased_at": "2026-10-01",
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 228},
    ],
    "total": 1072,
}

app.state.clock = FixedClock()  # 2026-10-02 18:00（JST）


# ---------------------------------------------------------------- 小道具

def read_json(total: int = 1072, prices: dict[int, int] | None = None, **over) -> str:
    d = copy.deepcopy(GOOD)
    for index, price in (prices or {}).items():
        d["items"][index]["price"] = price
    d.update(total=total, **over)
    return json.dumps(d, ensure_ascii=False)


def fake(*texts: str, stop_reason: str = "end_turn") -> FakeProvider:
    return FakeProvider([ChatResult(t, [], stop_reason, Usage(778, 104)) for t in texts])


def fresh_store() -> None:
    app.state.receipts = ReceiptStore()


async def post(raw: bytes, user: str = "u001", name: str = "receipt.png", ctype: str = "image/png") -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        return await c.post("/api/receipts/import", files={"file": (name, raw, ctype)}, headers={"x-user-id": user})


async def post_pdf(raw: bytes = PDF, user: str = "u001") -> httpx2.Response:
    return await post(raw, user, "receipt.pdf", "application/pdf")


async def mock_reset() -> None:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=5.0) as c:
        (await c.post("/_mock/reset")).raise_for_status()


async def mock_get(path: str) -> dict:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=5.0) as c:
        r = await c.get(path)
        r.raise_for_status()
        return r.json()


def rejected(r: httpx2.Response, status: int, type_: str, message: str) -> None:
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq((err["type"], err["message"]), (type_, message), "エラー本文")
    eq(err["request_id"], r.headers["x-request-id"], "request_id がヘッダーと同じ")


def without_id(body: dict) -> dict:
    assert RCP_ID.match(body["receipt_id"]), body["receipt_id"]
    return {k: v for k, v in body.items() if k != "receipt_id"}


def issue(index, name, reason) -> dict:
    return {"index": index, "name": name, "reason": reason, "message": MESSAGES[reason]}


def scanned_receipt() -> bytes:
    """receipt.png を絵として貼っただけの1ページの PDF（スキャンしたレシートと同じく、文字のデータが無い）。"""
    buf = io.BytesIO()
    with Image.open(io.BytesIO(PNG)) as img:
        img.convert("RGB").save(buf, "PDF", resolution=150)
    return buf.getvalue()


# ---------------------------------------------------------------- 検査

@check("V1 検証用のレシート（画像と PDF）と mockllm の receipt シナリオがそろっている")
async def _():
    eq(hashlib.sha256(PNG).hexdigest()[:12], EXPECTED_SHA12["receipt.png"], "receipt.png の SHA256 先頭12桁")
    eq(hashlib.sha256(PDF).hexdigest()[:12], EXPECTED_SHA12["receipt.pdf"], "receipt.pdf の SHA256 先頭12桁")
    with Image.open(io.BytesIO(PNG)) as img:
        eq(img.size, (600, 900), "receipt.png の寸法")
    found = {s["name"]: s["priority"] for s in (await mock_get("/_mock/scenarios"))["scenarios"]}
    eq(found.get("receipt"), 70, "receipt シナリオの priority")
    return "receipt.png 600×900・receipt.pdf・receipt（priority 70）あり"


@check("V2 画像は image ブロック、PDF は document ブロック。プロンプトとスキーマは同じ")
async def _():
    fresh_store()
    app.state.llm = f = fake(read_json(), read_json())
    eq([(await post(PNG)).status_code, (await post_pdf()).status_code], [201, 201], "status")
    blocks = [req.messages[0]["content"][0] for req in f.requests]
    eq([(b["type"], b["source"]["media_type"]) for b in blocks],
       [("image", "image/jpeg"), ("document", "application/pdf")], "1つ目のブロック")
    eq([req.messages[0]["content"][1]["text"] for req in f.requests], [RECEIPT_PROMPT] * 2, "プロンプト")
    eq([req.output_schema is RECEIPT_SCHEMA for req in f.requests], [True, True], "スキーマ")
    return "png → image（image/jpeg）・pdf → document（application/pdf）・同じプロンプトとスキーマ"


@check("V3 mockllm で receipt.png を取り込む：4品・合計 1,072円・要確認なし。input 778・output 104")
async def _():
    fresh_store()
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        r = await post(PNG)
    finally:
        await client.close()
    eq(r.status_code, 201, f"status（本文 {r.text}）")
    eq(without_id(r.json()), {
        "source": "image", **GOOD, "needs_review": False, "issues": [], "text_checked": False,
        "usage": {"input_tokens": 778, "output_tokens": 104},
    }, "応答")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"receipt": 1}, "mockllm のシナリオ")
    return "input 778（4+3+726+45）・output 104・text_checked=False"


@check("V4 mockllm で receipt.pdf を取り込む：PDF の文字と突き合わせて一致。input 1652・output 104")
async def _():
    fresh_store()
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        r = await post_pdf()
    finally:
        await client.close()
    eq(r.status_code, 201, f"status（本文 {r.text}）")
    eq(without_id(r.json()), {
        "source": "pdf", **GOOD, "needs_review": False, "issues": [], "text_checked": True,
        "usage": {"input_tokens": 1652, "output_tokens": 104},
    }, "応答")
    return "input 1652（4+3+1600+45）・output 104・text_checked=True"


@check("V5 pypdf で receipt.pdf の文字を先に読む：購入日・合計・金額・品名を拾える")
def _():
    text = parse_receipt_text(extract_text(PDF))
    assert text is not None, "文字を抜き出せませんでした"
    eq((text.purchased_at, text.total, sorted(text.amounts)),
       ("2026-10-01", 1072, [198, 228, 248, 398, 1072]), "購入日・合計・金額")
    eq([squash(i["name"]) in text.squashed for i in GOOD["items"]], [True] * 4, "品名がすべて見つかる")
    eq(parse_receipt_text(extract_text(scanned_receipt())), None, "画像だけの PDF")
    return "2026-10-01・合計 1072・金額 [198, 228, 248, 398, 1072]・画像だけの PDF は None"


@check("V6 合計が合わない結果（FakeProvider）は捨てずに needs_review。再試行はしない")
async def _():
    fresh_store()
    app.state.llm = f = fake(read_json(total=1000))
    r = await post(PNG)
    eq(r.status_code, 201, f"status（本文 {r.text}）")
    body = r.json()
    eq((body["needs_review"], body["issues"], body["total"], len(body["items"])),
       (True, [issue(None, None, "total_mismatch")], 1000, 4), "要確認の印")
    eq(len(f.requests), 1, "LLM の呼び出し回数")
    return "total 1000（明細の合計 1072）→ total_mismatch・呼び出し1回"


@check("V7 PDF：明細と合計がつじつまの合う読み違い（キャベツ 189・合計 1063）も、PDF の文字との突き合わせで見つかる")
async def _():
    fresh_store()
    app.state.llm = fake(read_json(total=1063, prices={1: 189}))
    body = (await post_pdf()).json()
    eq((body["needs_review"], body["issues"]),
       (True, [issue(None, None, "text_mismatch"), issue(1, "キャベツ", "text_mismatch")]), "要確認の印")
    return "total_mismatch なし・text_mismatch（全体）・text_mismatch（1 キャベツ）"


@check("V8 整合性検査：日付の形・存在しない日・未来の日・金額の範囲")
def _():
    today = date(2026, 10, 2)
    cases = [
        {},
        {"purchased_at": "2026/10/01"},
        {"purchased_at": "2026-02-30"},
        {"purchased_at": "2026-10-03"},
        {"prices": {3: 0}, "total": 844},
    ]
    got = []
    for case in cases:
        read = ReceiptRead.model_validate_json(read_json(**case))
        got.append([(i["reason"], i["index"]) for i in check_receipt(read, today)])
    eq(got, [
        [],
        [("invalid_date", None)],
        [("invalid_date", None)],
        [("invalid_date", None)],
        [("price_out_of_range", 3)],
    ], "検査の結果")
    return "正常→なし・2026/10/01→invalid_date・2026-02-30→invalid_date・2026-10-03→invalid_date・牛乳 0円→price_out_of_range"


@check("V9 形が崩れた応答だけ1回再試行：壊れた JSON → 正しい JSON は 201（usage 2回分）、2回とも壊れていれば 502")
async def _():
    fresh_store()
    app.state.llm = fake('{"store": "こんだて', read_json())
    r = await post(PNG)
    eq((r.status_code, r.json()["usage"]), (201, {"input_tokens": 1556, "output_tokens": 208}), "再試行で回復")
    fresh_store()
    app.state.llm = fake(read_json(items=[]), '{"store": "こんだて')
    rejected(await post(PNG), 502, "invalid_output", "読み取り結果の形式が正しくありませんでした")
    fresh_store()
    app.state.llm = f = fake(read_json(), stop_reason="max_tokens")
    rejected(await post(PNG), 502, "invalid_output", "読み取り結果の形式が正しくありませんでした")
    eq(len(f.requests), 1, "max_tokens は再試行しない")
    return "壊れた JSON→再試行で 201（1556／208）・items 空＋壊れた JSON→502・max_tokens→502（1回）"


@check("V10 二重取り込み：同じ利用者×同じ SHA256 は LLM を呼ばずに 409、失敗した取り込みは数えない")
async def _():
    fresh_store()
    app.state.llm = f = fake(*[read_json()] * 3)
    r1 = await post(PNG)
    r2 = await post(PNG, name="IMG_0001.png")
    r3 = await post(PNG, user="u002")
    r4 = await post_pdf()
    eq([r.status_code for r in (r1, r2, r3, r4)], [201, 409, 201, 201], "status")
    rejected(r2, 409, "duplicate", "このレシートはすでに取り込み済みです")
    eq(len(f.requests), 3, "LLM の呼び出し回数（2回目は呼ばない）")
    fresh_store()
    app.state.llm = fake('{"store": "こんだて', '{"store": "こんだて', read_json())
    eq([(await post(PNG)).status_code, (await post(PNG)).status_code], [502, 201], "失敗のあとの再送")
    return "同じ画像→409・別の利用者→201・同じレシートの PDF→201（SHA256 が違う）・502 のあとの再送→201"


@check("V11 受付：画像でも PDF でもない→415、10MiB 超→413、x-user-id の形式違い・file なし→422、画像だけの PDF は突き合わせなし")
async def _():
    fresh_store()
    app.state.llm = f = fake(read_json())
    rejected(await post("鶏むね肉 398円\n".encode(), name="receipt.png"), 415, "unsupported_media", MSG_UNSUPPORTED)
    rejected(await post(b"%PDF-" + b"x" * LIMIT), 413, "too_large", "ファイルは 10MB 以下にしてください")
    rejected(await post(PNG, user="admin"), 422, "invalid_request", "入力値が正しくありません：x-user-id")
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        rejected(await c.post("/api/receipts/import"), 422, "invalid_request", "入力値が正しくありません：file")
    r = await post_pdf(scanned_receipt())
    body = r.json()
    eq((r.status_code, body["source"], body["text_checked"], body["needs_review"]), (201, "pdf", False, False), "画像だけの PDF")
    eq(f.requests[0].messages[0]["content"][0]["type"], "document", "送ったブロック")
    return "テキスト→415・10MiB 超→413・admin→422・file なし→422・画像だけの PDF→201（text_checked=False）"


@check("V12 上流が 529 を返し続けると 503 upstream_unavailable（生のエラー文は返さない）")
async def _():
    fresh_store()
    client = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
    app.state.llm = AnthropicProvider(client)
    try:
        r = await post(PNG)
    finally:
        await client.close()
    rejected(r, 503, "upstream_unavailable", "レシートの読み取りに失敗しました。時間をおいて試してください")
    assert "overloaded" not in r.text, r.text
    return r.json()["error"]["message"]


finish("session07")
