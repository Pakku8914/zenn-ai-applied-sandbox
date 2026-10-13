"""セッション5の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session05

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE を切り替えなくてよい）。
mockllm に recipe_pdf_ask シナリオ（mockllm/fixtures/recipe_pdf_ask.json）が入っている必要がある。
入っていなければ docker compose up -d --build --wait mockllm でイメージを作り直す。
"""

from __future__ import annotations

import hashlib
import io
import json
import re

import httpx2
from anthropic import Anthropic, AsyncAnthropic
from pypdf import PdfWriter

from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.media import EXPECTED_SHA12, media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session05.app import SYSTEM_PROMPT, DocumentStore, app
from src.session05.compare import DUMMY_FILE_ID, count_input_tokens, scanned_pdf
from src.session05.documents import (
    check_citation,
    estimate_pdf_tokens,
    estimate_text_tokens,
    extract_pages,
    file_block,
    normalize,
    pdf_block,
    text_block,
)

BOOK = media_path("recipe_book.pdf").read_bytes()
QUESTION = "肉じゃがは何人分ですか？"            # 12文字×3バイト＝36バイト → 12トークン
OTHER_QUESTION = "生姜焼きの調理時間は何分ですか？"  # 「何人分」を含まない → recipe_pdf シナリオ
FIXTURE_QUOTE = "調理時間 35分　4人分"             # recipe_pdf_ask が返す引用文（1ページ目に実在する）
DOC_ID = re.compile(r"^doc_[0-9A-HJKMNP-TV-Z]{26}$")
MOCK = get_settings().mockllm_url
LIMIT = get_settings().upload_max_bytes

sync_client = Anthropic()


# ---------------------------------------------------------------- 小道具

async def call(method: str, path: str, **kw) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(method, path, **kw)


async def register(raw: bytes = BOOK, user: str = "u001", name: str = "recipe_book.pdf", ctype: str = "application/pdf") -> httpx2.Response:
    return await call("POST", "/api/documents", files={"file": (name, raw, ctype)}, headers={"x-user-id": user})


async def ask(doc_id: str, question: str, user: str = "u001", **extra) -> httpx2.Response:
    return await call("POST", f"/api/documents/{doc_id}/ask", json={"question": question, **extra}, headers={"x-user-id": user})


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


def pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def answer_json(page: int, quote: str, answer: str = "肉じゃがは4人分です。") -> str:
    return json.dumps({"answer": answer, "citations": [{"page": page, "quote": quote}]}, ensure_ascii=False)


def fake(*texts: str) -> FakeProvider:
    return FakeProvider([ChatResult(t, [], "end_turn", Usage(4888, 38)) for t in texts])


def fresh_store() -> None:
    app.state.documents = DocumentStore()


# ---------------------------------------------------------------- 検査

@check("V1 検証用の PDF と mockllm のシナリオがそろっている")
async def _():
    eq(hashlib.sha256(BOOK).hexdigest()[:12], EXPECTED_SHA12["recipe_book.pdf"], "recipe_book.pdf の SHA256 先頭12桁")
    eq(len(extract_pages(BOOK)), 3, "ページ数")
    found = {s["name"]: s["priority"] for s in (await mock_get("/_mock/scenarios"))["scenarios"]}
    assert "recipe_pdf_ask" in found, "recipe_pdf_ask がありません。docker compose up -d --build --wait mockllm で作り直してください"
    eq(found["recipe_pdf_ask"], 65, "recipe_pdf_ask の priority")
    return "recipe_book.pdf 3ページ・recipe_pdf_ask（priority 65）あり"


@check("V2 document ブロックの3つの渡し方：PDF のまま 4807・file 参照 1607・抜き出した文字は式どおりで5分の1以下")
def _():
    text = "\n".join(extract_pages(BOOK))
    eq(estimate_pdf_tokens(3), 4800, "見積もり（3ページ×1600）")
    eq(count_input_tokens(sync_client, [pdf_block(BOOK)]), 4807, "PDF のまま")
    eq(count_input_tokens(sync_client, [file_block(DUMMY_FILE_ID)]), 1607, "file 参照")
    n = count_input_tokens(sync_client, [text_block(text)])
    eq(n, 7 + estimate_text_tokens(text), "抜き出した文字（7＋ceil(バイト数/3)）")
    assert n * 5 <= 4807, f"抜き出した文字が PDF のままの5分の1を超えている（{n}）"
    return "base64=4807・file=1607・text=7＋ceil(バイト数/3)"


@check("V3 画像だけの PDF は PDF のままなら 1607 で数えられるが、pypdf では文字が1字も抜けない")
def _():
    scan = scanned_pdf()
    eq(len(extract_pages(scan)), 1, "ページ数")
    eq(normalize("".join(extract_pages(scan))), "", "抜き出せた文字")
    eq(count_input_tokens(sync_client, [pdf_block(scan)]), 1607, "PDF のまま")
    return "1ページ・抜き出せた文字 0 字・PDF のまま 1607"


@check("V4 引用の照合：mockllm が返す引用文は1ページ目にだけあり、短すぎる・範囲外・創作の引用は通らない")
def _():
    eq(normalize("R029　調理時間 35分\n4人分"), "R029調理時間35分4人分", "空白・改行の除去")
    eq(normalize("⾁じゃが"), "肉じゃが", "康熙部首の「⾁」は NFKC で「肉」になる")
    pages = extract_pages(BOOK)
    cases = [(1, FIXTURE_QUOTE), (2, FIXTURE_QUOTE), (3, FIXTURE_QUOTE), (1, "4人分"), (4, FIXTURE_QUOTE), (1, "材料（2人分）")]
    got = [check_citation(pages, p, q).reason for p, q in cases]
    eq(got, ["ok", "not_found", "not_found", "too_short", "page_out_of_range", "not_found"], "照合の結果")
    return "1ページ→ok・2/3ページ→not_found・「4人分」→too_short・4ページ→page_out_of_range・創作→not_found"


@check("V5 POST /api/documents：doc_＋ULID を振り、同じ内容は同じ ID（200）、別の利用者・1バイト違いは別の ID（201）")
async def _():
    fresh_store()
    r1 = await register()
    eq(r1.status_code, 201, f"1回目（本文 {r1.text}）")
    body = r1.json()
    eq(sorted(body), ["document_id", "pages", "sha256"], "応答の項目")
    assert DOC_ID.match(body["document_id"]), body["document_id"]
    eq((body["pages"], body["sha256"]), (3, hashlib.sha256(BOOK).hexdigest()), "pages・sha256")
    r2 = await register(name="renamed.pdf")
    r3 = await register(user="u002")
    r4 = await register(raw=BOOK + b"\n% kondate\n")
    eq([r.status_code for r in (r2, r3, r4)], [200, 201, 201], "2〜4回目の status")
    ids = [r.json()["document_id"] for r in (r1, r2, r3, r4)]
    eq((ids[1] == ids[0], ids[2] == ids[0], ids[3] == ids[0]), (True, False, False), "1回目と同じ ID か")
    return "同じ内容（名前違い）→200 同じ ID・別の利用者→201 別 ID・1バイト違い→201 別 ID"


@check("V6 受付の検査：PDF 以外は 415、201 ページと 10MiB 超は 413、x-user-id の形式違いは 422")
async def _():
    fresh_store()
    rejected(await register(media_path("receipt.png").read_bytes(), name="a.pdf"), 415, "unsupported_media", "PDF を送ってください")
    rejected(await register(b"%PDF-1.7\n" + "これは PDF ではありません\n".encode() * 20), 415, "unsupported_media", "PDF を送ってください")
    rejected(await register(pdf_bytes(201)), 413, "too_large", "PDF は 200 ページ以下にしてください")
    rejected(await register(b"%PDF-" + b"x" * LIMIT), 413, "too_large", "ファイルは 10MB 以下にしてください")
    rejected(await register(user="admin"), 422, "invalid_request", "入力値が正しくありません：x-user-id")
    return "PNG→415・偽の PDF→415・201ページ→413・10MiB 超→413・x-user-id=admin→422"


@check("V7 ask（mockllm）：答え・ページ・引用文が返り、引用は1ページ目で確かめられる。usage は 4888／38")
async def _():
    fresh_store()
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        doc_id = (await register()).json()["document_id"]
        r = await ask(doc_id, QUESTION)
    finally:
        await client.close()
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    eq(r.json(), {
        "answer": "肉じゃがは4人分です。",
        "citations": [{"page": 1, "quote": FIXTURE_QUOTE}],
        "usage": {"input_tokens": 4888, "output_tokens": 38},
    }, "応答")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"recipe_pdf_ask": 1}, "mockllm のシナリオ")
    return "肉じゃがは4人分です。（1ページ「調理時間 35分　4人分」）・input 4888（4+3+4800+12+69）・output 38"


@check("V8 ask（mockllm）：引用が文書に無い応答は、再試行しても直らず 502 invalid_output（呼び出しは2回）")
async def _():
    fresh_store()
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        doc_id = (await register()).json()["document_id"]
        r = await ask(doc_id, OTHER_QUESTION)
    finally:
        await client.close()
    rejected(r, 502, "invalid_output", "回答の根拠を文書の中で確かめられませんでした")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"recipe_pdf": 2}, "mockllm のシナリオ")
    return "recipe_pdf の引用「quoteのサンプル1」は文書に無い → 2回呼んで 502"


@check("V9 ask（FakeProvider）：1回目の引用がページ違いでも、2回目が正しければ 200。usage は2回分の合計")
async def _():
    fresh_store()
    doc_id = (await register()).json()["document_id"]
    app.state.llm = f = fake(answer_json(2, FIXTURE_QUOTE), answer_json(1, FIXTURE_QUOTE))
    r = await ask(doc_id, QUESTION)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    eq((r.json()["citations"], r.json()["usage"]), ([{"page": 1, "quote": FIXTURE_QUOTE}], {"input_tokens": 9776, "output_tokens": 76}), "引用と usage")
    req = f.requests[0]
    block = req.messages[0]["content"][0]
    eq((len(f.requests), block["type"], block["source"]["type"], block["source"]["media_type"]), (2, "document", "base64", "application/pdf"), "送ったリクエスト")
    eq((req.system, req.output_schema is not None), (SYSTEM_PROMPT, True), "system と構造化出力の指定")
    return "1回目 2ページ（not_found）→ 2回目 1ページ（ok）・usage 9776／76"


@check("V10 ask（FakeProvider）：JSON が壊れていても再試行で回復し、引用0件が2回続けば 502")
async def _():
    fresh_store()
    doc_id = (await register()).json()["document_id"]
    app.state.llm = fake('{"answer": "肉じゃがは', answer_json(1, FIXTURE_QUOTE))
    eq((await ask(doc_id, QUESTION)).status_code, 200, "壊れた JSON → 正しい JSON")
    empty = json.dumps({"answer": "4人分です。", "citations": []}, ensure_ascii=False)
    app.state.llm = fake(empty, empty)
    rejected(await ask(doc_id, QUESTION), 502, "invalid_output", "回答の根拠を文書の中で確かめられませんでした")
    return "壊れた JSON → 再試行で 200・引用0件×2 → 502"


@check("V11 ask：他人の文書・存在しない ID は 404、question が空なら 422、pages を付けても本章では結果が変わらない")
async def _():
    fresh_store()
    doc_id = (await register()).json()["document_id"]
    app.state.llm = fake(answer_json(1, FIXTURE_QUOTE), answer_json(1, FIXTURE_QUOTE))
    rejected(await ask(doc_id, QUESTION, user="u002"), 404, "not_found", "文書が見つかりません")
    rejected(await ask("doc_01J00000000000000000000000", QUESTION), 404, "not_found", "文書が見つかりません")
    rejected(await ask(doc_id, ""), 422, "invalid_request", "入力値が正しくありません：question")
    plain = (await ask(doc_id, QUESTION)).json()
    with_pages = (await ask(doc_id, QUESTION, pages=[1])).json()
    eq(with_pages, plain, "pages の有無で応答が同じ")
    return "u002→404・無い ID→404・空の question→422・pages=[1] は受け取るだけ"


@check("V12 上流が 529 を返し続けると 503 upstream_unavailable（生のエラー文は返さない）")
async def _():
    fresh_store()
    doc_id = (await register()).json()["document_id"]
    client = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
    app.state.llm = AnthropicProvider(client)
    try:
        r = await ask(doc_id, QUESTION)
    finally:
        await client.close()
    rejected(r, 503, "upstream_unavailable", "文書の読み取りに失敗しました。時間をおいて試してください")
    assert "overloaded" not in r.text, r.text
    return r.json()["error"]["message"]


sync_client.close()
finish("session05")
