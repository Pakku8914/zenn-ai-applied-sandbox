"""中間プロジェクト1の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/mid01

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE を切り替えなくてよい）。役割を分けて確かめる：
- 冷蔵庫の写真とレシートは mockllm に実際に送る（トークン数と、同じ入力で同じ結果になること）
- レシピ本の取り込みの中身は、答えを知っている Fake（src/mid01/fakes.py）で決定的に確かめる
- 失敗と要確認は FakeProvider で作る
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import logging

import httpx2
from anthropic import AsyncAnthropic
from pypdf import PdfWriter

from kondate.clock import FixedClock
from kondate.jobs import FINISHED
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.media import EXPECTED_SHA12, media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.mid01.app import app, reset_state
from src.mid01.fakes import RecipeReaderFake
from src.mid01.pantry import split_label

logging.getLogger("src.mid01").setLevel(logging.ERROR)  # 失敗を作ったときの警告で出力が乱れないように

MEDIA = {name: media_path(name).read_bytes()
         for name in ("fridge.jpg", "receipt.png", "receipt.pdf", "recipe_book.pdf", "recipe_book_full.pdf")}
FRIDGE, PNG, PDF = MEDIA["fridge.jpg"], MEDIA["receipt.png"], MEDIA["receipt.pdf"]
BOOK, FULL = MEDIA["recipe_book.pdf"], MEDIA["recipe_book_full.pdf"]
MOCK = get_settings().mockllm_url
LIMIT = get_settings().upload_max_bytes
MODEL = get_settings().llm_model
NAMES = ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]
SUMMARY = ("pages", "chunks", "imported", "duplicates_removed", "conflicts", "missing_pages", "unreadable_chunks", "needs_review")

# mockllm の fridge_photo が返す5件
FRIDGE_ITEMS = [
    {"name": "キャベツ", "quantity": "1/2玉", "amount": 0.5, "unit": "玉", "confidence": 0.94, "category": "野菜"},
    {"name": "鶏むね肉", "quantity": "1枚", "amount": 1, "unit": "枚", "confidence": 0.88, "category": "肉"},
    {"name": "卵", "quantity": "4個", "amount": 4, "unit": "個", "confidence": 0.97, "category": "卵"},
    {"name": "にんじん", "quantity": "1本", "amount": 1, "unit": "本", "confidence": 0.81, "category": "野菜"},
    {"name": "牛乳", "quantity": "1本", "amount": 1, "unit": "本", "confidence": 0.9, "category": "乳製品"},
]
# mockllm の receipt が返すレシート
RECEIPT = {
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


# ---------------------------------------------------------------- 小道具

def fresh() -> None:
    reset_state(app, FixedClock())  # 2026-10-02 18:00（JST）。検査ごとにイベントループが変わるのでジョブキューも作り直す


def use_mockllm() -> AsyncAnthropic:
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    return client


async def call(method: str, path: str, user: str = "u001", **kw) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test", timeout=60.0) as c:
        return await c.request(method, path, headers={"x-user-id": user}, **kw)


async def upload(path: str, field: str, raw: bytes, name: str, ctype: str, user: str) -> httpx2.Response:
    return await call("POST", path, user, files={field: (name, raw, ctype)})


async def scan(raw: bytes = FRIDGE, user: str = "u001", name: str = "fridge.jpg") -> httpx2.Response:
    return await upload("/api/fridge/scan", "image", raw, name, "image/jpeg", user)


async def receipt(raw: bytes = PNG, user: str = "u001", name: str = "receipt.png", ctype: str = "image/png") -> httpx2.Response:
    return await upload("/api/receipts/import", "file", raw, name, ctype, user)


async def register(raw: bytes = BOOK, user: str = "u001") -> httpx2.Response:
    return await upload("/api/documents", "file", raw, "book.pdf", "application/pdf", user)


async def pantry(user: str = "u001") -> dict:
    r = await call("GET", "/api/pantry", user)
    eq(r.status_code, 200, f"GET /api/pantry（本文 {r.text}）")
    return r.json()


async def recipes(user: str = "u001", **params) -> dict:
    r = await call("GET", "/api/pantry/recipes", user, params=params)
    eq(r.status_code, 200, f"GET /api/pantry/recipes（本文 {r.text}）")
    return r.json()


async def start_import(doc_id: str, user: str = "u001") -> str:
    r = await call("POST", f"/api/documents/{doc_id}/import-recipes", user)
    eq(r.status_code, 202, f"status（本文 {r.text}）")
    return r.json()["job_id"]


async def until(cond, what: str) -> None:
    for _ in range(6000):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"待ちきれませんでした：{what}")


async def finished(job_id: str) -> dict:
    await until(lambda: app.state.jobs.get(job_id).status in FINISHED, "ジョブの終了")
    return (await call("GET", f"/api/jobs/{job_id}")).json()


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


def stock(p: dict) -> list[tuple]:
    """在庫を (名前, [(数量, 単位)…]) の並びにする。"""
    return [(i["name"], [(a["amount"], a["unit"]) for a in i["amounts"]]) for i in p["items"]]


def review_rows(p: dict) -> list[tuple]:
    return [(x["name"], x["amount"], x["unit"], x["source"]["type"], x["source"]["index"], x["reasons"]) for x in p["to_review"]]


def item(name: str, confidence: float = 0.9) -> dict:
    return {"name": name, "quantity": "1個", "amount": 1, "unit": "個", "confidence": confidence, "category": "野菜"}


def fridge_answer(items: list[dict]) -> ChatResult:
    return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(1668, 120))


def receipt_answer(total: int = 1072, items: list[dict] | None = None) -> ChatResult:
    d = copy.deepcopy(RECEIPT)
    d["total"] = total
    if items is not None:
        d["items"] = items
    return ChatResult(json.dumps(d, ensure_ascii=False), [], "end_turn", Usage(778, 104))


def pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def without_id(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "receipt_id"}


# ---------------------------------------------------------------- 検査

@check("V1 検証用の画像・PDF 5点と mockllm のシナリオ（fridge_photo・receipt）がそろい、/health が ok")
async def _():
    for name, raw in MEDIA.items():
        eq(hashlib.sha256(raw).hexdigest()[:12], EXPECTED_SHA12[name], f"{name} の SHA256 先頭12桁")
    found = {s["name"] for s in (await mock_get("/_mock/scenarios"))["scenarios"]}
    assert {"fridge_photo", "receipt"} <= found, f"シナリオが足りません：{sorted(found)}"
    r = await call("GET", "/health")
    eq((r.status_code, r.json()["status"]), (200, "ok"), "GET /health")
    return "画像・PDF 5点・fridge_photo と receipt あり・/health ok"


@check("V2 mockllm：写真の読み取りはセッション4と同じ応答（usage 1668/194・EXIF なし）で、在庫に5品が確認済みで入る")
async def _():
    fresh()
    await mock_reset()
    client = use_mockllm()
    try:
        r = await scan()
    finally:
        await client.close()
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    eq(list(body), ["ingredients", "needs_review", "issues", "image", "usage"], "応答の項目")
    eq((body["ingredients"], body["needs_review"], body["usage"]),
       (FRIDGE_ITEMS, False, {"input_tokens": 1668, "output_tokens": 194}), "食材・要確認・usage")
    eq((body["image"]["bytes"], body["image"]["exif_removed"]), (89080, True), "送った画像")
    p = await pantry()
    eq(stock(p), [("キャベツ", [(0.5, "玉")]), ("鶏むね肉", [(1, "枚")]), ("卵", [(4, "個")]),
                  ("にんじん", [(1, "本")]), ("牛乳", [(1, "本")])], "在庫")
    eq((p["to_review"], p["items"][0]["sources"]), ([], [{"type": "fridge", "index": 0}]), "要確認・キャベツの出どころ")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"fridge_photo": 1}, "mockllm のシナリオ")
    return "キャベツ 0.5玉・鶏むね肉 1枚・卵 4個・にんじん 1本・牛乳 1本／要確認なし"


@check("V3 mockllm：続けてレシート（PNG）を取り込むと同じ名前にまとまり、「卵（10個入り）」は卵 10個として 4個に足される")
async def _():
    fresh()
    await mock_reset()
    client = use_mockllm()
    try:
        r1 = await scan()
        r2 = await receipt()
    finally:
        await client.close()
    eq((r1.status_code, r2.status_code), (200, 201), f"status（本文 {r2.text}）")
    rid = r2.json()["receipt_id"]
    eq((r2.json()["needs_review"], r2.json()["usage"]), (False, {"input_tokens": 778, "output_tokens": 104}), "レシート")
    p = await pantry()
    eq(stock(p), [
        ("キャベツ", [(0.5, "玉"), (1, "点")]),
        ("鶏むね肉", [(1, "枚"), (1, "点")]),
        ("卵", [(14, "個")]),
        ("にんじん", [(1, "本")]),
        ("牛乳", [(1, "本"), (1, "点")]),
    ], "在庫")
    eq(p["items"][2]["sources"], [{"type": "fridge", "index": 2}, {"type": "receipt", "id": rid, "index": 2}], "卵の出どころ")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"fridge_photo": 1, "receipt": 1}, "mockllm のシナリオ")
    eq([split_label(s) for s in ("卵（10個入り）", "卵(６個入)", "牛乳", "めんつゆ（3倍濃縮）")],
       [("卵", (10, "個")), ("卵", (6, "個")), ("牛乳", None), ("めんつゆ（3倍濃縮）", None)], "表記のそろえ方")
    return "卵 4個＋10個入り×1＝14個・キャベツ 0.5玉＋1点・鶏むね肉 1枚＋1点・牛乳 1本＋1点"


@check("V4 mockllm：PDF のレシートは文字と突き合わせて 201（usage 1652/104）、同じ PDF の2回目は LLM を呼ばずに 409")
async def _():
    fresh()
    await mock_reset()
    client = use_mockllm()
    try:
        r1 = await receipt(PDF, "u002", "receipt.pdf", "application/pdf")
        r2 = await receipt(PDF, "u002", "receipt.pdf", "application/pdf")
    finally:
        await client.close()
    eq(r1.status_code, 201, f"status（本文 {r1.text}）")
    b = r1.json()
    eq((b["source"], b["text_checked"], b["needs_review"], b["usage"]),
       ("pdf", True, False, {"input_tokens": 1652, "output_tokens": 104}), "1回目")
    rejected(r2, 409, "duplicate", "このレシートはすでに取り込み済みです")
    eq(stock(await pantry("u002")), [("鶏むね肉", [(1, "点")]), ("キャベツ", [(1, "点")]), ("卵", [(10, "個")]),
                                     ("牛乳", [(1, "点")])], "u002 の在庫（1回分だけ）")
    eq(stock(await pantry("u001")), [], "u001 の在庫（他人のレシートは混ざらない）")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"receipt": 1}, "mockllm のシナリオ（2回目は呼ばない）")
    return "201（pdf・text_checked=True）→ 409 duplicate・u002 の在庫は1回分・u001 は空"


@check("V5 Fake：レシピ本（3ページ）の取り込みが成功すると目録に載り、scope=books はそこに載っているレシピだけを探す")
async def _():
    fresh()
    app.state.llm = FakeProvider([fridge_answer(FRIDGE_ITEMS)])
    eq((await scan()).status_code, 200, "写真")
    r = await register()
    eq((r.status_code, r.json()["pages"]), (201, 3), "レシピ本の登録")
    doc_id = r.json()["document_id"]
    before = await recipes(scope="books")
    app.state.llm = fake = RecipeReaderFake()
    result = (await finished(await start_import(doc_id)))["result"]
    eq({k: result[k] for k in SUMMARY}, {"pages": 3, "chunks": 1, "imported": 3, "duplicates_removed": 0, "conflicts": [],
                                          "missing_pages": [], "unreadable_chunks": [], "needs_review": False}, "取り込みの結果")
    eq([(x["id"], x["page"]) for x in result["recipes"]], [("R029", 1), ("R011", 2), ("R084", 3)], "取り込んだレシピ")
    eq((result["usage"], fake.calls), ({"input_tokens": 4800, "output_tokens": 115}, 1), "usage と呼び出し回数")
    every, books = await recipes(), await recipes(scope="books")
    eq(before["recipes"], [], "取り込む前の scope=books")
    eq([(x["id"], x["in_books"]) for x in every["recipes"]],
       [("R064", []), ("R067", []), ("R001", []), ("R025", []), ("R095", [])], "scope=all")
    eq([(x["id"], x["name"], x["in_books"]) for x in books["recipes"]],
       [("R029", "肉じゃが", [{"document_id": doc_id, "page": 1}])], "scope=books")
    eq((every["ingredients"], every["scope"], books["scope"], every["to_review_count"]), (NAMES, "all", "books", 0), "応答の項目")
    return "取り込み 3件（R029・R011・R084）・input 4800／all→R064,R067,R001,R025,R095・books→R029（1ページ）"


@check("V6 受付：偽装ファイルは 415、201ページの PDF と 10MiB 超は 413。LLM を呼ばず、在庫も利用量も増えない")
async def _():
    fresh()
    app.state.llm = never = FakeProvider([])  # 呼ばれたら RuntimeError
    text = "鶏むね肉 1枚\n".encode()
    big = pdf_bytes(201)
    rejected(await scan(text), 415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像を送ってください")
    rejected(await scan(PDF), 415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像を送ってください")
    rejected(await register(PNG), 415, "unsupported_media", "PDF を送ってください")
    rejected(await receipt(text), 415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像か PDF を送ってください")
    rejected(await register(big), 413, "too_large", "PDF は 200 ページ以下にしてください")
    rejected(await receipt(big, name="receipt.pdf", ctype="application/pdf"), 413, "too_large", "PDF は 200 ページ以下にしてください")
    rejected(await register(b"%PDF-" + b"x" * LIMIT), 413, "too_large", "ファイルは 10MB 以下にしてください")
    rejected(await scan(b"\xff\xd8\xff" + b"x" * LIMIT), 413, "too_large", "画像は 10MB 以下にしてください")
    eq((len(never.requests), await pantry(), app.state.usage.records), (0, {"items": [], "to_review": []}, []),
       "LLM の呼び出し・在庫・利用量")
    return "テキスト→415・PDF を写真として→415・PNG を本として→415・201ページ→413（2窓口）・10MiB 超→413（2窓口）"


@check("V7 FakeProvider：確からしさの低い食材と辞書に無い名前は to_review に分かれ、検索には確認済みだけを使う。502 では在庫が変わらない")
async def _():
    fresh()
    items = [item("キャベツ", 0.94), item("鶏ムネ肉", 0.9), item("にんじん", 0.42), item("ズッキーニ", 0.35), item("卵", 0.6)]
    bad = [item("キャベツ", 1.5)] + items[1:]
    app.state.llm = FakeProvider([fridge_answer(items), fridge_answer(bad), fridge_answer(bad)])
    r = await scan()
    eq((r.status_code, r.json()["needs_review"], len(r.json()["issues"])), (200, True, 4), "写真の応答")
    p = await pantry()
    eq(stock(p), [("キャベツ", [(1, "個")]), ("卵", [(1, "個")])], "在庫（確認済みだけ）")
    eq(review_rows(p), [
        ("鶏ムネ肉", 1, "個", "fridge", 1, ["unknown_name"]),
        ("にんじん", 1, "個", "fridge", 2, ["low_confidence"]),
        ("ズッキーニ", 1, "個", "fridge", 3, ["low_confidence", "unknown_name"]),
    ], "要確認")
    found = await recipes()
    eq((found["ingredients"], [x["id"] for x in found["recipes"]], found["to_review_count"]),
       (["キャベツ", "卵"], ["R119", "R039", "R038", "R064", "R067"], 3), "作れるレシピ")
    rejected(await scan(), 502, "invalid_output", "読み取り結果の形式が正しくありませんでした")
    eq(stock(await pantry()), [("キャベツ", [(1, "個")]), ("卵", [(1, "個")])], "502 のあとの在庫（前の写真のまま）")
    totals = app.state.usage.totals("u001")
    eq((totals["input_tokens"], totals["output_tokens"]), (5004, 360), "利用量（502 の2回分も含む）")
    return "在庫 キャベツ・卵／要確認 3件／検索 R119,R039,R038,R064,R067／502 のあとも在庫は同じ・input 5004"


@check("V8 FakeProvider：レシート全体の問題は全行を、行の問題・辞書に無い名前・個数0 はその行だけを to_review に回す")
async def _():
    fresh()
    odd = [
        {"name": "鶏むね肉", "quantity": 0, "price": 398},
        {"name": "ティッシュ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 0},
    ]
    app.state.llm = FakeProvider([receipt_answer(total=1000), receipt_answer(total=844, items=odd)])
    r1 = await receipt(user="u003")
    eq((r1.status_code, [i["reason"] for i in r1.json()["issues"]]), (201, ["total_mismatch"]), "合計が合わないレシート")
    p3 = await pantry("u003")
    eq((stock(p3), review_rows(p3)), ([], [
        ("鶏むね肉", 1, "点", "receipt", 0, ["total_mismatch"]),
        ("キャベツ", 1, "点", "receipt", 1, ["total_mismatch"]),
        ("卵", 10, "個", "receipt", 2, ["total_mismatch"]),
        ("牛乳", 1, "点", "receipt", 3, ["total_mismatch"]),
    ]), "u003 の在庫と要確認")
    r2 = await receipt(user="u004")
    eq([(i["index"], i["reason"]) for i in r2.json()["issues"]], [(3, "price_out_of_range")], "行の問題")
    p4 = await pantry("u004")
    eq((stock(p4), review_rows(p4)), ([("卵", [(10, "個")])], [
        ("鶏むね肉", 0, "点", "receipt", 0, ["invalid_quantity"]),
        ("ティッシュ", 1, "点", "receipt", 1, ["unknown_name"]),
        ("牛乳", 1, "点", "receipt", 3, ["price_out_of_range"]),
    ]), "u004 の在庫と要確認")
    return "total_mismatch→4行とも要確認／個数0→invalid_quantity・ティッシュ→unknown_name・牛乳 0円→price_out_of_range"


@check("V9 mockllm：同じ写真・同じレシートを別の利用者が送っても、読み取り結果と在庫は同じ（決定的）")
async def _():
    fresh()
    await mock_reset()
    client = use_mockllm()
    try:
        a1, a5 = await scan(user="u001"), await scan(user="u005")
        b1, b5 = await receipt(user="u001"), await receipt(user="u005")
    finally:
        await client.close()
    eq(a1.json(), a5.json(), "写真の読み取り結果")
    eq(without_id(b1.json()), without_id(b5.json()), "レシートの読み取り結果（receipt_id 以外）")
    eq(stock(await pantry("u001")), stock(await pantry("u005")), "在庫")
    reqs = (await mock_get("/_mock/stats"))["requests"]
    eq([(q["scenario"], q["input_tokens"], q["output_tokens"]) for q in reqs],
       [("fridge_photo", 1668, 194)] * 2 + [("receipt", 778, 104)] * 2, "mockllm が受けた4回")
    return "写真 2回とも 1668/194・レシート 2回とも 778/104・在庫も同じ"


@check("V10 通しの流れ（写真→レシート→レシピ本）：利用量は1回1件で記録され、u001 の合計は input 7246・output 413")
async def _():
    fresh()
    await mock_reset()
    client = use_mockllm()
    try:
        eq([(await scan()).status_code, (await receipt()).status_code], [200, 201], "写真とレシート")
    finally:
        await client.close()
    doc_id = (await register()).json()["document_id"]
    app.state.llm = RecipeReaderFake()
    eq((await finished(await start_import(doc_id)))["status"], "succeeded", "取り込みジョブ")
    found = await recipes(scope="books")
    eq([x["id"] for x in found["recipes"]], ["R029"], "取り込んだ本から作れるレシピ")
    log = app.state.usage
    eq([(r.user_id, r.kind, r.model, r.input_tokens, r.output_tokens) for r in log.records], [
        ("u001", "llm", MODEL, 1668, 194),
        ("u001", "llm", MODEL, 778, 104),
        ("u001", "llm", MODEL, 4800, 115),
    ], "利用量の記録")
    totals = log.totals("u001")
    eq((totals["input_tokens"], totals["output_tokens"], log.totals("u002")["input_tokens"]), (7246, 413, 0), "合計")
    return "記録 3件（写真 1668/194・レシート 778/104・取り込み 4800/115）・合計 7246/413・u002 は 0"


@check("V11 取り込みを途中で取り消すと目録には載らないが、取り消すまでに使った3回分（input 48000）は記録される")
async def _():
    fresh()
    app.state.llm = fake = RecipeReaderFake(gate_at=4)  # gate を渡さないので、4回目の呼び出しで待ち続ける
    doc_id = (await register(FULL)).json()["document_id"]
    job_id = await start_import(doc_id)
    await until(lambda: fake.calls == 4, "4回目の呼び出し")
    r = await call("DELETE", f"/api/jobs/{job_id}")
    eq((r.status_code, r.json()["status"], r.json()["done"], r.json()["total"]), (200, "cancelled", 3, 14), "DELETE の応答")
    eq((app.state.books, app.state.usage.totals("u001")["input_tokens"]), ({}, 48_000), "目録と利用量")
    return "cancelled 3/14・目録は空・input 48000（10ページ×1600×3回）"


@check("V12 他人の在庫は見えない。scope・limit・x-user-id の形式違いは 422、在庫が空なら検索しない")
async def _():
    fresh()
    app.state.llm = FakeProvider([fridge_answer(FRIDGE_ITEMS)])
    eq((await scan(user="u001")).status_code, 200, "u001 の写真")
    eq(await pantry("u002"), {"items": [], "to_review": []}, "u002 の在庫")
    eq(await recipes("u002"), {"ingredients": [], "scope": "all", "recipes": [], "to_review_count": 0}, "u002 の作れるレシピ")
    rejected(await call("GET", "/api/pantry/recipes", params={"scope": "shelf"}), 422, "invalid_request", "入力値が正しくありません：scope")
    rejected(await call("GET", "/api/pantry/recipes", params={"limit": 11}), 422, "invalid_request", "入力値が正しくありません：limit")
    rejected(await call("GET", "/api/pantry", user="admin"), 422, "invalid_request", "入力値が正しくありません：x-user-id")
    return "u002 は空・scope=shelf→422・limit=11→422・admin→422"


finish("mid01")
