"""セッション6の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session06

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE を切り替えなくてよい）。
役割を分けて確かめる：トークン数とキャッシュは mockllm に実際に送って測り、
取り込みの中身（件数・ID・統合・取りこぼし）は答えを知っている Fake（src/session06/fakes.py）で決定的に確かめる。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re

import anthropic
import httpx2
from anthropic import Anthropic, AsyncAnthropic
from pypdf import PdfReader, PdfWriter

from kondate.data import load_recipes
from kondate.jobs import FINISHED, JobQueue
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.media import EXPECTED_SHA12, media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish, sse_events
from src.session06 import cache_demo
from src.session06.app import app
from src.session06.documents import estimate_pdf_tokens, extract_pages, normalize, pdf_block
from src.session06.fakes import RecipeReaderFake
from src.session06.importer import CHUNK_OVERLAP, CHUNK_PAGES, IMPORT_PROMPT, IMPORT_SYSTEM
from src.session06.pages import base64_size, build_index, chunk_ranges, guess_pages, parse_heading, select_pages, split_pdf

FULL = media_path("recipe_book_full.pdf").read_bytes()
BOOK = media_path("recipe_book.pdf").read_bytes()
FULL_TEXTS = extract_pages(FULL)
INDEX = build_index(FULL_TEXTS)
RECIPES = load_recipes()
QUESTION = "肉じゃがは何人分ですか？"     # 36バイト → 12トークン
FIXTURE_QUOTE = "調理時間 35分　4人分"   # recipe_pdf_ask が返す引用文（R029 のページに実在する）
JOB_ID = re.compile(r"^job_[0-9A-HJKMNP-TV-Z]{26}$")
SUMMARY = ("pages", "chunks", "imported", "duplicates_removed", "conflicts", "missing_pages", "unreadable_chunks", "needs_review")
MOCK = get_settings().mockllm_url
MODEL = get_settings().llm_model

sync_client = Anthropic()


# ---------------------------------------------------------------- 小道具

async def call(method: str, path: str, user: str = "u001", **kw) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test", timeout=60.0) as c:
        return await c.request(method, path, headers={"x-user-id": user}, **kw)


async def register(raw: bytes = FULL, user: str = "u001") -> str:
    r = await call("POST", "/api/documents", user=user, files={"file": ("book.pdf", raw, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    return r.json()["document_id"]


async def ask(doc_id: str, question: str = QUESTION, user: str = "u001", **extra) -> httpx2.Response:
    return await call("POST", f"/api/documents/{doc_id}/ask", user=user, json={"question": question, **extra})


async def start_import(doc_id: str) -> str:
    r = await call("POST", f"/api/documents/{doc_id}/import-recipes")
    eq(r.status_code, 202, f"status（本文 {r.text}）")
    eq(sorted(r.json()), ["job_id"], "応答の項目")
    assert JOB_ID.match(r.json()["job_id"]), r.text
    return r.json()["job_id"]


def job(job_id: str):
    return app.state.jobs.get(job_id)


async def until(cond, what: str) -> None:
    for _ in range(6000):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"待ちきれませんでした：{what}")


async def finished(job_id: str) -> dict:
    await until(lambda: job(job_id).status in FINISHED, "ジョブの終了")
    return (await call("GET", f"/api/jobs/{job_id}")).json()


async def events(job_id: str, user: str = "u001") -> tuple[httpx2.Response, list[dict]]:
    """ASGITransport は応答を最後まで受け取ってから返すので、ジョブが終わるまで戻らない。"""
    r = await call("GET", f"/api/jobs/{job_id}/events", user=user)
    return r, [e for e in sse_events(r.text.splitlines()) if e["event"]]


async def run_import(fake: RecipeReaderFake) -> dict:
    fresh_jobs()
    app.state.llm = fake
    job_id = await start_import(await register())
    return (await finished(job_id))["result"]


def fresh_jobs() -> None:
    app.state.jobs = JobQueue(concurrency=1)  # 検査ごとにイベントループが変わるので、キューも作り直す
    app.state.job_owners = {}


async def mock_reset() -> None:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=5.0) as c:
        (await c.post("/_mock/reset")).raise_for_status()


async def mock_get(path: str) -> dict:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=5.0) as c:
        r = await c.get(path)
        r.raise_for_status()
        return r.json()


def count(*blocks: dict, system: str | None = None) -> int:
    kw = {"system": system} if system else {}
    return sync_client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": list(blocks)}], **kw).input_tokens


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


def headings(raw: bytes) -> list[str]:
    return [parse_heading(t, i).recipe_id for i, t in enumerate(extract_pages(raw), 1)]


def expected_rows() -> list[tuple]:
    return [(r["id"], normalize(r["name"]), r["minutes"], r["servings"], r["kcal"]) for r in RECIPES]


def answer_json(page: int, quote: str) -> str:
    return json.dumps({"answer": "肉じゃがは4人分です。", "citations": [{"page": page, "quote": quote}]}, ensure_ascii=False)


# ---------------------------------------------------------------- 検査

@check("V1 検証用の PDF・共通データ・mockllm のシナリオがそろっている")
async def _():
    eq(hashlib.sha256(FULL).hexdigest()[:12], EXPECTED_SHA12["recipe_book_full.pdf"], "recipe_book_full.pdf の SHA256 先頭12桁")
    eq((len(FULL_TEXTS), len(RECIPES)), (120, 120), "ページ数と recipes.json の件数")
    found = {s["name"] for s in (await mock_get("/_mock/scenarios"))["scenarios"]}
    assert {"recipe_pdf", "recipe_pdf_ask"} <= found, f"シナリオが足りません：{sorted(found)}"
    return "recipe_book_full.pdf 120ページ・recipes.json 120件・recipe_pdf と recipe_pdf_ask あり"


@check("V2 送る前の見積もり：120ページは 192,000（count_tokens 192,007）、base64 は 4×ceil(バイト数/3)、601ページは API が 400")
def _():
    eq(estimate_pdf_tokens(120), 192_000, "見積もり（120×1600）")
    block = pdf_block(FULL)
    eq(count(block), 192_007, "count_tokens（枠の 7 を含む）")
    eq(len(block["source"]["data"]), base64_size(len(FULL)), "base64 の長さ")
    try:
        count(pdf_block(pdf_bytes(601)))
    except anthropic.BadRequestError:
        pass
    else:
        raise AssertionError("601ページが 400 になりませんでした")
    return "120ページ→192,000＋枠 7・base64 は約 4/3 倍・601ページ→400 invalid_request_error"


@check("V3 見出しの索引：120ページの ID・料理名・数値が recipes.json と一致し、質問から当たりを付けられる")
def _():
    eq([h.page for h in INDEX], list(range(1, 121)), "索引のページ番号")
    eq([(h.recipe_id, h.name, h.minutes, h.servings, h.kcal) for h in INDEX], expected_rows(), "ID・料理名・調理時間・人数・kcal")
    got = [guess_pages(INDEX, q) for q in (QUESTION, "豆腐ハンバーグは何人分ですか？", "おすすめはどれですか？")]
    eq(got, [[29], [33, 34], []], "当たり")
    return "120件一致・「肉じゃが」→[29]・「豆腐ハンバーグ」→[33, 34]・「おすすめ」→[]"


@check("V4 ページ選択：[29] は1ページで 1607、[11, 29, 84] は3ページで 4807")
def _():
    one, three = select_pages(FULL, [29]), select_pages(FULL, [11, 29, 84])
    eq((headings(one), headings(three)), (["R029"], ["R011", "R029", "R084"]), "選んだ PDF の見出し")
    eq((count(pdf_block(one)), count(pdf_block(three))), (1607, 4807), "count_tokens")
    return "[29]→R029・1607／[11, 29, 84]→R011・R029・R084・4807"


@check("V5 ask（mockllm）：pages=[29] の引用は元の29ページ。1回目はキャッシュ作成 1676、2回目（索引で自動選択）は読み出し 1676")
async def _():
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        doc_id = await register()
        r1 = await ask(doc_id, pages=[29])
        r2 = await ask(doc_id)
    finally:
        await client.close()
    base = {"answer": "肉じゃがは4人分です。", "citations": [{"page": 29, "quote": FIXTURE_QUOTE}]}
    eq((r1.status_code, r2.status_code), (200, 200), f"status（本文 {r1.text} / {r2.text}）")
    eq(r1.json(), {**base, "usage": {"input_tokens": 12, "output_tokens": 38,
                                     "cache_creation_input_tokens": 1676, "cache_read_input_tokens": 0}}, "1回目")
    eq(r2.json(), {**base, "usage": {"input_tokens": 12, "output_tokens": 38,
                                     "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1676}}, "2回目")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"recipe_pdf_ask": 2}, "mockllm のシナリオ")
    return "1回目 input 12・作成 1676（4+69+3+1600）／2回目 input 12・読み出し 1676"


@check("V6 キャッシュは接頭辞が 1024 以上のときだけ：PDF 1ページは2回目に読み出し、抜き出した文字だけでは作成も読み出しも 0")
def _():
    rows = cache_demo.run()
    eq(rows["pdf"], [(12, 1676, 0), (12, 0, 1676)], "PDF 1ページ（input, 作成, 読み出し）")
    eq([(made, read) for _, made, read in rows["text"]], [(0, 0), (0, 0)], "抜き出した文字（作成, 読み出し）")
    eq(rows["text"][0][0], rows["text"][1][0], "抜き出した文字の input は2回とも同じ")
    return "PDF 1ページ：作成 1676 → 読み出し 1676／抜き出した文字：作成 0・読み出し 0（2回とも）"


@check("V7 ask の pages：範囲外・21個・空・当たりなしは 422（LLM を呼ばない）。送った PDF のページ番号は元の番号に戻す")
async def _():
    full_id, small_id = await register(), await register(BOOK)
    results = [ChatResult(answer_json(p, FIXTURE_QUOTE), [], "end_turn", Usage(100, 38)) for p in (2, 1)]
    app.state.llm = f = FakeProvider(results)
    out_of_range = "pages は 1〜120 の範囲で指定してください"
    rejected(await ask(full_id, pages=[0]), 422, "invalid_request", out_of_range)
    rejected(await ask(full_id, pages=[121]), 422, "invalid_request", out_of_range)
    rejected(await ask(full_id, pages=list(range(1, 22))), 422, "invalid_request", "pages は 1〜20 個で指定してください")
    rejected(await ask(full_id, pages=[]), 422, "invalid_request", "pages は 1〜20 個で指定してください")
    rejected(await ask(full_id, "おすすめはどれですか？"), 422, "invalid_request",
             "読むページを決められませんでした。pages でページ番号を指定してください")
    eq(len(f.requests), 0, "422 では LLM を呼ばない")
    r = await ask(full_id, pages=[84, 29, 29, 11])
    eq((r.status_code, r.json()["citations"]), (200, [{"page": 29, "quote": FIXTURE_QUOTE}]), "送った PDF の2ページ目 → 元の29ページ")
    sent = base64.b64decode(f.requests[0].messages[0]["content"][0]["source"]["data"])
    eq(headings(sent), ["R011", "R029", "R084"], "送ったページ（昇順・重複なし）")
    eq((await ask(small_id)).status_code, 200, "3ページの文書（pages なし）")
    block = f.requests[1].messages[0]["content"][0]
    eq((block["source"]["data"] == base64.standard_b64encode(BOOK).decode("ascii"), block["cache_control"]),
       (True, {"type": "ephemeral"}), "小さな文書は元の PDF をそのまま送る（キャッシュの印つき）")
    return "422 が5通り・[84, 29, 29, 11]→R011・R029・R084 を送り引用は29ページ・3ページの文書は丸ごと"


@check("V8 分割：10ページずつ1ページ重ねて14個・送るのは133ページ。count_tokens の合計 214,032（1回で送ると 192,088）")
def _():
    ranges = chunk_ranges(120, CHUNK_PAGES, CHUNK_OVERLAP)
    eq((len(ranges), ranges[:2], ranges[-1]), (14, [(1, 10), (10, 19)], (118, 120)), "範囲")
    parts = split_pdf(FULL, ranges)
    eq([len(PdfReader(io.BytesIO(p)).pages) for p in parts], [10] * 13 + [3], "各 PDF のページ数")
    prompt = {"type": "text", "text": IMPORT_PROMPT}
    eq(sum(count(pdf_block(p), prompt, system=IMPORT_SYSTEM) for p in parts), 214_032, "14回分の入力")
    eq(count(pdf_block(FULL), prompt, system=IMPORT_SYSTEM), 192_088, "1回で送る場合")
    return "14個・133ページ・214,032（133×1600＋14×88）／1回なら 192,088"


@check("V9 取り込みジョブ（Fake）：202 → progress 0〜14 → done。120件の ID・料理名・数値が recipes.json と一致し、重複13件を除く")
async def _():
    fresh_jobs()
    gate = asyncio.Event()
    app.state.llm = fake = RecipeReaderFake(gate_at=1, gate=gate)
    doc_id = await register()
    job_id = await start_import(doc_id)
    await until(lambda: fake.calls == 1, "1回目の呼び出し")
    listening = asyncio.create_task(events(job_id))
    await until(lambda: bool(job(job_id)._listeners), "SSE の購読")  # 検査のためだけに中を覗く
    gate.set()
    r, evs = await listening
    eq(r.headers["content-type"].split(";")[0], "text/event-stream", "content-type")
    eq([e["event"] for e in evs], ["progress"] * 16 + ["done"], "イベントの並び")
    eq([(e["data"]["status"], e["data"]["done"], e["data"]["total"]) for e in evs[:-1]],
       [("running", i, 14) for i in range(15)] + [("succeeded", 14, 14)], "progress の中身")
    result = evs[-1]["data"]["result"]
    eq({k: result[k] for k in SUMMARY}, {"pages": 120, "chunks": 14, "imported": 120, "duplicates_removed": 13, "conflicts": [],
                                          "missing_pages": [], "unreadable_chunks": [], "needs_review": False}, "結果の要約")
    eq([(x["id"], x["name"], x["minutes"], x["servings"], x["kcal"]) for x in result["recipes"]], expected_rows(), "120件の中身")
    eq([x["page"] for x in result["recipes"]], list(range(1, 121)), "元の PDF でのページ番号")
    eq((result["document_id"], result["usage"]["input_tokens"], fake.calls), (doc_id, 212_800, 14), "document_id・入力・呼び出し回数")
    snap = (await call("GET", f"/api/jobs/{job_id}")).json()
    eq((snap["status"], snap["done"], snap["total"], snap["result"] == result), ("succeeded", 14, 14, True), "GET のスナップショット")
    return "progress 16件（running 0〜14・succeeded 14）→ done・120件一致・重複除去 13・input 212,800"


@check("V10 取りこぼしと食い違い（Fake）：重ねたページで読み落としを回収し、回収できない読み落としと食い違いは needs_review")
async def _():
    a = await run_import(RecipeReaderFake(skip_once=["R019"]))
    b = await run_import(RecipeReaderFake(skip_once=["R050"]))
    c = await run_import(RecipeReaderFake(misread_once={"R010": 10}))
    eq((a["imported"], a["duplicates_removed"], a["missing_pages"], a["needs_review"]), (120, 12, [], False), "R019 を1回読み落とす")
    eq((b["imported"], b["duplicates_removed"], b["missing_pages"], b["needs_review"]), (119, 13, [50], True), "R050 を読み落とす")
    r010 = next(x for x in c["recipes"] if x["id"] == "R010")
    eq((c["imported"], c["duplicates_removed"], c["conflicts"], c["needs_review"], r010["minutes"]),
       (120, 12, ["R010"], True, RECIPES[9]["minutes"] + 10), "R010 の調理時間を1回読み違える")
    return "R019→19ページ（重ねたページ）で回収・R050→missing_pages [50]・R010→conflicts ['R010']（先に読んだ値を残す）"


@check("V11 読めない範囲（Fake）：2個目の範囲が2回とも壊れた JSON なら、11〜18ページが取りこぼしになる")
async def _():
    fake = RecipeReaderFake(broken_calls=[2, 3])
    r = await run_import(fake)
    eq((r["imported"], r["duplicates_removed"], r["missing_pages"], r["unreadable_chunks"], r["needs_review"], fake.calls),
       (112, 11, list(range(11, 19)), [2], True, 15), "結果と呼び出し回数")
    return "112件・重複除去 11・missing_pages 11〜18・unreadable_chunks [2]・呼び出し 15回"


@check("V12 mockllm で取り込むと、作られた ID（idのサンプル1）は検証で落ち、14個の範囲すべてが「読めなかった」になる")
async def _():
    fresh_jobs()
    await mock_reset()
    client = AsyncAnthropic()
    app.state.llm = AnthropicProvider(client)
    try:
        job_id = await start_import(await register())
        result = (await finished(job_id))["result"]
    finally:
        await client.close()
    eq((result["imported"], result["unreadable_chunks"], len(result["missing_pages"]), result["needs_review"]),
       (0, list(range(1, 15)), 120, True), "結果")
    eq(result["usage"]["input_tokens"], 2 * 214_032, "入力（再試行を含めて2回ずつ）")
    eq((await mock_get("/_mock/stats"))["by_scenario"], {"recipe_pdf": 28}, "mockllm のシナリオ")
    return "0件・unreadable_chunks 1〜14・input 428,064（14個×2回）・recipe_pdf 28回"


@check("V13 キャンセル：4個目の範囲で止まっている間に DELETE すると cancelled（done 3/14）。途中までの結果は残さない")
async def _():
    fresh_jobs()
    app.state.llm = fake = RecipeReaderFake(gate_at=4)  # gate を渡さないので、4回目の呼び出しで待ち続ける
    job_id = await start_import(await register())
    await until(lambda: fake.calls == 4, "4回目の呼び出し")
    before = (await call("GET", f"/api/jobs/{job_id}")).json()
    r = await call("DELETE", f"/api/jobs/{job_id}")
    again = await call("DELETE", f"/api/jobs/{job_id}")
    _, evs = await events(job_id)
    after = (await call("GET", f"/api/jobs/{job_id}")).json()
    eq((before["status"], before["done"], before["total"]), ("running", 3, 14), "取り消す前")
    eq((r.status_code, r.json()), (200, {"job_id": job_id, "status": "cancelled", "done": 3, "total": 14}), "DELETE の応答")
    eq((again.status_code, again.json()["status"]), (200, "cancelled"), "2回目の DELETE")
    eq([(e["event"], e["data"]["status"], e["data"]["done"]) for e in evs], [("progress", "cancelled", 3)], "取り消したあとの SSE")
    eq((after["result"], fake.calls), (None, 4), "結果と呼び出し回数")
    return "running 3/14 → DELETE → cancelled 3/14・SSE は progress(cancelled) だけ・result は null"


@check("V14 上流が 529 を返し続けると、ジョブは failed になり、SSE は error（upstream_unavailable）で終わる")
async def _():
    fresh_jobs()
    client = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
    app.state.llm = AnthropicProvider(client)
    try:
        job_id = await start_import(await register(BOOK))
        snap = await finished(job_id)
    finally:
        await client.close()
    r, evs = await events(job_id)
    eq((snap["status"], snap["done"], snap["total"], snap["result"]), ("failed", 0, 1, None), "スナップショット")
    eq([e["event"] for e in evs], ["progress", "error"], "イベントの並び")
    eq(evs[1]["data"], {"type": "upstream_unavailable", "message": "文書の読み取りに失敗しました。時間をおいて試してください",
                        "request_id": r.headers["x-request-id"]}, "error の中身")
    assert "overloaded" not in r.text.lower(), r.text
    return "failed 0/1 → error「文書の読み取りに失敗しました。時間をおいて試してください」"


@check("V15 他人のジョブ・無いジョブは GET・SSE・DELETE とも 404、他人の文書は取り込めない（404）")
async def _():
    fresh_jobs()
    app.state.llm = RecipeReaderFake()
    doc_id = await register()
    job_id = await start_import(doc_id)
    msg = "ジョブが見つかりません"
    for method, path in (("GET", f"/api/jobs/{job_id}"), ("GET", f"/api/jobs/{job_id}/events"), ("DELETE", f"/api/jobs/{job_id}")):
        rejected(await call(method, path, user="u002"), 404, "not_found", msg)
    rejected(await call("GET", "/api/jobs/job_01J00000000000000000000000"), 404, "not_found", msg)
    rejected(await call("POST", f"/api/documents/{doc_id}/import-recipes", user="u002"), 404, "not_found", "文書が見つかりません")
    eq((await finished(job_id))["status"], "succeeded", "本人のジョブは最後まで動く")
    return "u002 の GET・SSE・DELETE→404・無いジョブ→404・他人の文書の取り込み→404"


sync_client.close()
finish("session06")
