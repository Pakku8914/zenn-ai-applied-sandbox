"""最終プロジェクトの検証①：HTTP API の一覧（写真・レシート・文書・ジョブ・音声の HTTP・自分のデータ・エラー）。

    docker compose exec api bash verify-all.sh src/final

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE が何であっても実行できる）。
トークン数は mockllm に実際に送って確かめ、取り込みの中身・音声の HTTP は偽物で決定的に確かめる。処理時間は合否に使わない。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import wave
import io
from urllib.parse import unquote

import numpy as np
from anthropic import AsyncAnthropic

from kondate.audio import float32_to_wav
from kondate.clock import FixedClock
from kondate.jobs import FINISHED
from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish, sse_events
from src.final.app import app
from src.final.evaluate import returning
from src.final.pantry import pantry_names
from src.final.testkit import (OUT, TEXT, FakeVoicevox, FixedTranscriber, RecipeReaderFake, fake_detector, mock,
                               running, swapped, voice_turn)
from src.final.web import get_llm

S = get_settings()
FRIDGE = media_path("fridge.jpg").read_bytes()
RECEIPT_PNG = media_path("receipt.png").read_bytes()
RECEIPT_PDF = media_path("receipt.pdf").read_bytes()
BOOK = media_path("recipe_book.pdf").read_bytes()
QUESTION = "肉じゃがは何人分ですか？"
FIXTURE_QUOTE = "調理時間 35分　4人分"
FRIDGE_NAMES = ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]
RECEIPT_KEYS = ["receipt_id", "source", "store", "purchased_at", "items", "total", "needs_review", "issues",
                "text_checked", "usage"]
ZERO_USAGE = {"llm": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0},
              "stt_seconds": 0.0, "tts_seconds": 0.0, "stt_processing_seconds": 0.0, "tts_processing_seconds": 0.0,
              "response_cache": {"hits": 0, "misses": 0}}


def ulid_of(prefix: str) -> re.Pattern:
    return re.compile(rf"^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$")


def h(user: str) -> dict:
    return {"x-user-id": user}


def err(r) -> tuple:
    return r.status_code, r.json()["error"]["type"], r.json()["error"]["message"]


@check("V1 GET /health は 200、GET /health/deps は依存先とウォームアップが整って 200（入口は空）")
async def _():
    async with running() as c:
        live = await c.get("/health")
        deps = await c.get("/health/deps")
    body = deps.json()
    eq((live.status_code, live.json()["status"]), (200, "ok"), "/health")
    eq((deps.status_code, body["status"], body["deps"], body["warmup"]),
       (200, "ok", {"mockllm": "ok", "voicevox": "ok"}, {}), f"/health/deps（本文 {body}）")
    eq([(g["concurrency"], g["max_waiting"], g["running"], g["waiting"]) for g in body["gates"].values()],
       [(1, 2, 0, 0), (1, 3, 0, 0)], "入口（stt・tts）")
    return "/health 200／/health/deps 200（mockllm ok・voicevox ok）／入口 stt 1+2・tts 1+3"


@check("V2 POST /api/uploads：中身で形式を決めて 201 で保存し、画像でも PDF でもないものは 415")
async def _():
    out = OUT / "http_v2"
    async with running(out=out) as c:
        r = await c.post("/api/uploads", files={"file": ("山田家の冷蔵庫.jpg", FRIDGE)})
        bad = await c.post("/api/uploads", files={"file": ("fridge.jpg", b"hello")})
        saved = sorted(p.name for p in (out / "uploads").iterdir())
    body = r.json()
    eq((r.status_code, list(body), body["kind"], body["bytes"], body["sha256"]),
       (201, ["upload_id", "kind", "bytes", "sha256"], "image", len(FRIDGE), hashlib.sha256(FRIDGE).hexdigest()),
       "fridge.jpg")
    assert ulid_of("up").match(body["upload_id"]), body
    eq(saved, [f"{body['upload_id']}.jpg"], "保存した名前（利用者のファイル名は使わない）")
    eq(err(bad), (415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"), "画像でない")
    return "fridge.jpg → 201（up_ + ULID.jpg で保存）／hello → 415 unsupported_media"


@check("V3 POST /api/fridge/scan：1回目 miss 1668/194・2回目 hit 0/0。要確認なしの5品を手元の食材に残す")
async def _():
    await mock("POST", "/_mock/reset")
    async with running() as c:
        r1 = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)})
        r2 = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)})
        pantry = pantry_names(app.state.data, "u001")
        u = (await c.get("/api/usage")).json()
    stats = await mock("GET", "/_mock/stats")
    b1 = r1.json()
    eq((r1.status_code, r1.headers["x-cache"], list(b1)),
       (200, "miss", ["ingredients", "needs_review", "issues", "image", "usage"]), f"1回目（本文 {r1.text}）")
    eq(([i["name"] for i in b1["ingredients"]], b1["needs_review"], b1["issues"]), (FRIDGE_NAMES, False, []), "食材")
    eq((b1["image"]["exif_removed"], b1["image"]["bytes"], b1["usage"]),
       (True, 89080, {"input_tokens": 1668, "output_tokens": 194}), "前処理と usage")
    eq((r2.headers["x-cache"], r2.json()["usage"], r2.json()["ingredients"]),
       ("hit", {"input_tokens": 0, "output_tokens": 0}, b1["ingredients"]), "2回目")
    eq((stats["total"], pantry), (1, FRIDGE_NAMES), "mockllm が受けた数・手元の食材")
    eq((u["llm"]["input_tokens"], u["llm"]["output_tokens"], u["response_cache"]),
       (1668, 194, {"hits": 1, "misses": 1}), "GET /api/usage")
    return "miss 1668/194 → hit 0/0・mockllm total=1・手元の食材 キャベツ・鶏むね肉・卵・にんじん・牛乳"


@check("V4 POST /api/receipts/import：画像 778/104・同じ画像は LLM の前に 409・PDF は 1652/104 で文字と突き合わせる")
async def _():
    await mock("POST", "/_mock/reset")
    async with running(clock=FixedClock()) as c:
        png = await c.post("/api/receipts/import", files={"file": ("receipt.png", RECEIPT_PNG)}, headers=h("u002"))
        again = await c.post("/api/receipts/import", files={"file": ("receipt.png", RECEIPT_PNG)}, headers=h("u002"))
        pdf = await c.post("/api/receipts/import", files={"file": ("receipt.pdf", RECEIPT_PDF)}, headers=h("u002"))
        pantry = pantry_names(app.state.data, "u002")
    stats = await mock("GET", "/_mock/stats")
    p, d = png.json(), pdf.json()
    eq((png.status_code, list(p), p["source"], p["total"], p["needs_review"], p["text_checked"], p["usage"]),
       (201, RECEIPT_KEYS, "image", 1072, False, False, {"input_tokens": 778, "output_tokens": 104}),
       f"画像（本文 {png.text}）")
    assert ulid_of("rcp").match(p["receipt_id"]), p
    eq(err(again), (409, "duplicate", "このレシートはすでに取り込み済みです"), "同じ画像をもう一度")
    eq((pdf.status_code, d["source"], d["needs_review"], d["text_checked"], d["usage"]),
       (201, "pdf", False, True, {"input_tokens": 1652, "output_tokens": 104}), "PDF")
    eq((stats["total"], pantry), (2, ["鶏むね肉", "キャベツ", "卵", "牛乳"]), "mockllm が受けた数・手元の食材")
    return "画像 201 778/104 → 同じ画像 409（mockllm に送らない）→ PDF 201 1652/104・text_checked／手元の食材 4品"


@check("V5 文書：登録 201 → 同じ PDF は 200 で同じ ID。ask は作成 4876 → 命中 0、他人は 404、範囲外の pages は 422")
async def _():
    await mock("POST", "/_mock/reset")
    async with running() as c:
        d1 = await c.post("/api/documents", files={"file": ("recipe_book.pdf", BOOK)})
        d2 = await c.post("/api/documents", files={"file": ("recipe_book.pdf", BOOK)})
        doc_id = d1.json()["document_id"]
        a1 = await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION})
        a2 = await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION})
        other = await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION}, headers=h("u002"))
        wide = await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION, "pages": [5]})
        u = (await c.get("/api/usage")).json()
    eq((d1.status_code, d2.status_code, d1.json()["pages"], d2.json()["document_id"]), (201, 200, 3, doc_id), "登録")
    assert ulid_of("doc").match(doc_id), d1.text
    base = {"answer": "肉じゃがは4人分です。", "citations": [{"page": 1, "quote": FIXTURE_QUOTE}]}
    eq((a1.headers["x-cache"], a1.json()), ("miss", {**base, "usage": {
        "input_tokens": 12, "output_tokens": 38, "cache_creation_input_tokens": 4876, "cache_read_input_tokens": 0}}),
       f"1回目（本文 {a1.text}）")
    eq((a2.headers["x-cache"], a2.json()["usage"]), ("hit", {
        "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}), "2回目")
    eq(err(other), (404, "not_found", "文書が見つかりません"), "他人の文書")
    eq(err(wide), (422, "invalid_request", "pages は 1〜3 の範囲で指定してください"), "範囲外のページ")
    eq((u["llm"], u["response_cache"]), ({"input_tokens": 12, "output_tokens": 38, "cache_creation_input_tokens": 4876,
                                          "cache_read_input_tokens": 0}, {"hits": 1, "misses": 1}), "GET /api/usage")
    return "201 → 200（同じ ID）／ask miss 12/38・作成 4876 → hit 0／他人 404／pages [5] は 422"


@check("V6 取り込みジョブ：202 → 終わったら result に3件（R029・R011・R084）、SSE は progress → done。消したら 404")
async def _():
    fake = RecipeReaderFake()
    app.dependency_overrides[get_llm] = returning(fake)
    try:
        async with running() as c:
            doc_id = (await c.post("/api/documents", files={"file": ("recipe_book.pdf", BOOK)},
                                   headers=h("u003"))).json()["document_id"]
            started = await c.post(f"/api/documents/{doc_id}/import-recipes", headers=h("u003"))
            job_id = started.json()["job_id"]
            for _ in range(1000):
                snap = (await c.get(f"/api/jobs/{job_id}", headers=h("u003"))).json()
                if snap["status"] in FINISHED:
                    break
                await asyncio.sleep(0.01)
            sse = await c.get(f"/api/jobs/{job_id}/events", headers=h("u003"))
            stranger = await c.get(f"/api/jobs/{job_id}", headers=h("u004"))
            u = (await c.get("/api/usage", headers=h("u003"))).json()
            deleted = (await c.delete("/api/me/data", headers=h("u003"))).json()
            gone = await c.get(f"/api/jobs/{job_id}", headers=h("u003"))
    finally:
        app.dependency_overrides.clear()
    assert ulid_of("job").match(job_id), started.text
    result = snap["result"]
    eq((started.status_code, snap["status"], snap["done"], snap["total"]), (202, "succeeded", 1, 1), "ジョブ")
    eq((result["imported"], [r["id"] for r in result["recipes"]], [r["page"] for r in result["recipes"]],
        result["needs_review"], result["usage"]["input_tokens"]),
       (3, ["R029", "R011", "R084"], [1, 2, 3], False, 4800), "result")
    events = [e for e in sse_events(sse.text.splitlines()) if e["event"]]
    eq([e["event"] for e in events], ["progress", "done"], "SSE のイベント")
    eq(events[-1]["data"]["result"]["imported"], 3, "done の result")
    eq((err(stranger), u["llm"]["input_tokens"]), ((404, "not_found", "ジョブが見つかりません"), 4800),
       "他人のジョブ・利用量")
    eq((deleted["deleted"]["documents"], err(gone)), (1, (404, "not_found", "ジョブが見つかりません")),
       "DELETE /api/me/data のあとのジョブ")
    return "202 → succeeded（1/1）・3件・入力 4800／SSE progress → done／他人 404／自分のデータを消すと 404"


@check("V7 音声の HTTP（偽の認識と合成）：transcribe・speak（文ごとに合成してつなぐ・クレジット）・読む文字が無ければ 422")
async def _():
    fake = FakeVoicevox()
    silence_1s = float32_to_wav(np.zeros(16000, dtype=np.float32), 16000)
    async with running() as c:
        with swapped(app.state, transcriber=FixedTranscriber(TEXT), voicevox=fake):
            t = await c.post("/api/voice/transcribe", files={"audio": ("a.wav", silence_1s, "audio/wav")}, headers=h("u005"))
            bad = await c.post("/api/voice/transcribe", files={"audio": ("a.wav", b"RIFF0000JUNK")}, headers=h("u005"))
            s = await c.post("/api/voice/speak", json={"text": "鶏むね肉の塩炒めです。キャベツも入れます。"}, headers=h("u005"))
            empty = await c.post("/api/voice/speak", json={"text": "---"}, headers=h("u005"))
            u = (await c.get("/api/usage", headers=h("u005"))).json()
    with wave.open(io.BytesIO(s.content)) as wf:
        wav = (wf.getframerate(), wf.getnframes() / wf.getframerate())
    eq((t.status_code, t.json()), (200, {"text": TEXT, "audio_seconds": 1.0, "rtf": 0.0}), "transcribe")
    eq(err(bad), (415, "unsupported_media", "WAV（PCM 16bit）の音声を送ってください"), "WAV でない")
    eq((s.status_code, s.headers["content-type"], s.headers["x-voice-credit"], unquote(s.headers["x-voice-credit"])),
       (200, "audio/wav", "VOICEVOX:%E3%81%9A%E3%82%93%E3%81%A0%E3%82%82%E3%82%93", "VOICEVOX:ずんだもん"), "speak")
    eq((wav, fake.calls), ((24000, 2.625), 2), "WAV（24kHz・2文をつないだ長さ）と合成の回数")
    eq(err(empty), (422, "invalid_request", "入力値が正しくありません：text"), "読む文字が無い")
    eq((u["stt_seconds"], u["tts_seconds"]), (1.0, 2.625), "利用量")
    return "transcribe 200／WAV でない 415／speak 200（24kHz・2.625 秒・合成 2 回・クレジット）／--- は 422"


@check("V8 DELETE /api/me/data：台帳・利用記録・応答キャッシュを消し、GET /api/usage が全項目 0 になる。2回目は 0 件")
async def _():
    out = OUT / "http_v8"
    async with running(out=out) as c:
        await c.post("/api/uploads", files={"file": ("fridge.jpg", FRIDGE)}, headers=h("u004"))
        await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)}, headers=h("u004"))
        await c.post("/api/receipts/import", files={"file": ("receipt.png", RECEIPT_PNG)}, headers=h("u004"))
        doc_id = (await c.post("/api/documents", files={"file": ("recipe_book.pdf", BOOK)},
                               headers=h("u004"))).json()["document_id"]
        await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION}, headers=h("u004"))
        with swapped(app.state, transcriber=FixedTranscriber(TEXT), voicevox=FakeVoicevox(), make_detector=fake_detector):
            log, _ = await voice_turn(app, {"type": "start", "sample_rate": 16000, "store_audio": True}, "u004")
        before = (await c.get("/api/usage", headers=h("u004"))).json()
        missing = await c.delete("/api/me/data")
        first = await c.delete("/api/me/data", headers=h("u004"))
        second = await c.delete("/api/me/data", headers=h("u004"))
        after = (await c.get("/api/usage", headers=h("u004"))).json()
        pantry = pantry_names(app.state.data, "u004")
        files = sorted(p.name for d in ("uploads", "voice") for p in (out / d).iterdir())
        rescan = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)}, headers=h("u004"))
    eq("turn_end" in [m["type"] for m in log if isinstance(m, dict)], True, "声の1ターン")
    eq((before["response_cache"]["misses"] > 0, before["llm"]["input_tokens"] > 0), (True, True), "消す前")
    eq(err(missing), (422, "invalid_request", "入力値が正しくありません：x-user-id"), "x-user-id なし")
    eq(first.json(), {"deleted": {"uploads": 2, "documents": 1, "receipts": 1, "voice": 1, "usage": 6}}, "1回目")
    eq(second.json(), {"deleted": {"uploads": 0, "documents": 0, "receipts": 0, "voice": 0, "usage": 0}}, "2回目")
    eq((after, pantry, files), (ZERO_USAGE, [], []), "消したあとの利用量・手元の食材・ファイル")
    eq(rescan.headers["x-cache"], "miss", "消したあとの写真（応答キャッシュも消えている）")
    return ("x-user-id なし 422／1回目 uploads 2（ファイル＋食材名）・documents 1・receipts 1・voice 1・usage 6／"
            "2回目 0 件／GET /api/usage は全項目 0／同じ写真は miss")


@check("V9 エラー本文：上流の障害は固定文の 503、形の崩れは 502（2回分を記録）、x-user-id の形と大きさの検査")
async def _():
    broken = AsyncAnthropic(max_retries=0, default_headers={"x-mock-fault": "529"})
    bad_json = FakeProvider([ChatResult('{"ingredients": [{"name": ', [], "end_turn", Usage(10, 5))] * 2)
    try:
        async with running() as c:
            with swapped(app.state, llm=AnthropicProvider(broken)):
                down = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)}, headers=h("u006"))
                rdown = await c.post("/api/receipts/import", files={"file": ("receipt.png", RECEIPT_PNG)},
                                     headers=h("u006"))
            app.dependency_overrides[get_llm] = returning(bad_json)
            broken_out = await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)}, headers=h("u007"))
            app.dependency_overrides.clear()
            who = await c.get("/api/usage", headers=h("user1"))
            big = await c.post("/api/uploads", files={"file": ("big.jpg", bytes(S.upload_max_bytes + 1))})
            u6 = (await c.get("/api/usage", headers=h("u006"))).json()
            u7 = (await c.get("/api/usage", headers=h("u007"))).json()
    finally:
        app.dependency_overrides.clear()
        await broken.close()
    eq(err(down), (503, "upstream_unavailable", "画像の読み取りに失敗しました。時間をおいて試してください"), "写真の 503")
    eq(err(rdown), (503, "upstream_unavailable", "レシートの読み取りに失敗しました。時間をおいて試してください"), "レシートの 503")
    eq(("overloaded" in down.text, down.headers["x-request-id"] == down.json()["error"]["request_id"]), (False, True),
       "上流の生の文を返さない・request_id はヘッダと同じ")
    assert ulid_of("req").match(down.headers["x-request-id"]), down.headers
    eq(err(broken_out), (502, "invalid_output", "読み取り結果の形式が正しくありませんでした"), "形の崩れ")
    eq((u6["llm"]["input_tokens"], u7["llm"]["input_tokens"], u7["llm"]["output_tokens"]), (0, 20, 10),
       "利用量（503 は 0・502 は2回分）")
    eq(err(who), (422, "invalid_request", "入力値が正しくありません：x-user-id"), "x-user-id の形")
    eq(err(big), (413, "too_large", "ファイルは 10MB 以下にしてください"), "大きすぎるファイル")
    return "529 → 503（固定文・生の文なし）／形の崩れ → 502・2回分 20/10 を記録／user1 → 422／10MB 超 → 413"


finish("final-http")
