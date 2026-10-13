"""セッション14の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session14

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE が何であっても実行できる）。
合否はトークン数・件数・状態で決める。処理時間は合否に使わず、表示もしない。
同時実行数は時間ではなく、差し替えた遅い関数（Event が立つまで戻らない）で「同時に動いた数」「断った数」を数えて確かめる。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

import httpx2
import numpy as np

from kondate import stt
from kondate.audio import float32_to_wav
from kondate.clock import FixedClock
from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.media import media_path
from kondate.settings import get_settings
from kondate.tts import TtsResult
from kondate.usage import UsageLog
from kondate.verifykit import check, eq, finish
from src.session14 import estimate as est
from src.session14.app import FRIDGE_PROMPT, MSG_STT_BUSY, MSG_TTS_BUSY, PREPROCESS, app, get_llm
from src.session14.cache import ResponseCache, cache_key, sha256_hex
from src.session14.models import FRIDGE_SCHEMA
from src.session14.usage_book import UsageBook

S = get_settings()
FRIDGE = media_path("fridge.jpg").read_bytes()
BOOK = media_path("recipe_book.pdf").read_bytes()
QUESTION = "肉じゃがは何人分ですか？"
FIXTURE_QUOTE = "調理時間 35分　4人分"   # recipe_pdf_ask が返す引用文（1ページ目に実在する）
NO_WARMUP: dict = {}
ZERO_AUDIO = {"stt_seconds": 0.0, "tts_seconds": 0.0, "stt_processing_seconds": 0.0, "tts_processing_seconds": 0.0}


@asynccontextmanager
async def running(warmers: dict | None = NO_WARMUP) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を動かしてからアプリに直接投げる。warmers=None なら本物のウォームアップを使う。"""
    app.state.warmers = warmers
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            yield client


async def mock(method: str, path: str) -> dict:
    async with httpx2.AsyncClient(base_url=S.mockllm_url, timeout=10) as c:
        r = await c.request(method, path)
        r.raise_for_status()
        return r.json()


async def scan(c: httpx2.AsyncClient, user: str = "u001", raw: bytes = FRIDGE) -> httpx2.Response:
    return await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", raw, "image/jpeg")}, headers={"x-user-id": user})


async def usage_of(c: httpx2.AsyncClient, user: str) -> dict:
    return (await c.get("/api/usage", headers={"x-user-id": user})).json()


async def settle(gate, n: int) -> None:
    """n 件すべてが入口に着く（受け付けられるか断られる）まで待つ。待ち方は合否に関係しない。"""
    for _ in range(3000):
        if gate.inflight + gate.rejected >= n:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"入口に着いた数が {n} になりませんでした：{gate.stats()}")


def base_key(**over) -> str:
    material = dict(scope="u001", kind="fridge_scan", content_sha256=sha256_hex(FRIDGE), preprocess=PREPROCESS,
                    prompt=FRIDGE_PROMPT, system=None, model=S.llm_model, schema=FRIDGE_SCHEMA)
    material.update(over)
    return cache_key(**material)


@check("V1 キャッシュキー：同じ材料なら同じキー、材料を1つでも変えると別のキー（6通り）")
def _():
    eq(base_key(), base_key(), "同じ材料")
    eq(base_key(preprocess=dict(reversed(list(PREPROCESS.items())))), base_key(), "辞書の並び順だけ違う")
    variants = [
        base_key(content_sha256=sha256_hex(FRIDGE + b"\x00")),
        base_key(preprocess={**PREPROCESS, "jpeg_quality": 85}),
        base_key(prompt=FRIDGE_PROMPT + "調味料は除いてください。"),
        base_key(model=S.llm_model_light),
        base_key(schema={**FRIDGE_SCHEMA, "description": "冷蔵庫の食材"}),
        base_key(scope="u002"),
    ]
    eq(len({base_key(), *variants}), 7, "異なるキーの数")
    return "並び順だけ違う→同じキー・内容／前処理／プロンプト／モデル／スキーマ／利用者の6通りはすべて別のキー"


@check("V2 ResponseCache：最近使ったものを残して追い出す・forget で利用者の分を消す・保持時間で期限切れ")
def _():
    clock = FixedClock()
    c = ResponseCache(clock, max_entries=2, ttl_seconds=60)
    u = Usage(1, 1)
    c.put("a", "u001", {"v": "a"}, u)
    c.put("b", "u001", {"v": "b"}, u)
    eq(c.get("a").value, {"v": "a"}, "a を使う")
    c.put("c", "u002", {"v": "c"}, u)                       # 3件目：いちばん長く使われていない b を追い出す
    eq([k for k in ("a", "b", "c") if c.get(k) is not None], ["a", "c"], "残ったキー")
    eq(c.forget("u001"), 1, "u001 の分を消した件数")
    clock.advance(59)
    eq(c.get("c") is not None, True, "59 秒後")
    clock.advance(1)
    eq((c.get("c"), len(c)), (None, 0), "60 秒後")
    return "a を使ってから3件目→b を追い出す・forget(u001) 1 件・59 秒は命中・60 秒で期限切れ"


@check("V3 冷蔵庫の写真を2回：1回目は mockllm で 1668/194、2回目は命中して 0/0（mockllm の total は 1 のまま）")
async def _():
    await mock("POST", "/_mock/reset")
    async with running() as c:
        r1 = await scan(c)
        r2 = await scan(c)
        u = await usage_of(c, "u001")
    stats = await mock("GET", "/_mock/stats")
    eq((r1.status_code, r2.status_code), (200, 200), f"status（本文 {r1.text}）")
    eq((r1.headers["x-cache"], r2.headers["x-cache"]), ("miss", "hit"), "x-cache")
    eq(list(r1.json()), ["ingredients", "image", "usage"], "応答の項目")
    eq(r1.json()["usage"], {"input_tokens": 1668, "output_tokens": 194}, "1回目の usage")
    eq(r2.json()["usage"], {"input_tokens": 0, "output_tokens": 0}, "2回目の usage")
    eq(r2.json()["ingredients"], r1.json()["ingredients"], "2回目の食材")
    eq(stats["total"], 1, "mockllm が受けた数")
    eq(u, {"llm": {"input_tokens": 1668, "output_tokens": 194, "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0},
           **ZERO_AUDIO, "response_cache": {"hits": 1, "misses": 1}}, "GET /api/usage")
    return "miss 1668/194 → hit 0/0・mockllm total=1・利用量 1668/194・命中 1／外れ 1"


@check("V4 PDF：プロンプトキャッシュ（作成 4876→読み出し 4876）と応答キャッシュ（LLM を呼ばない）の違い")
async def _():
    await mock("POST", "/_mock/reset")

    async def ask(c, user: str) -> tuple[httpx2.Response, httpx2.Response]:
        d = await c.post("/api/documents", files={"file": ("recipe_book.pdf", BOOK, "application/pdf")},
                         headers={"x-user-id": user})
        doc_id = d.json()["document_id"]
        a = await c.post(f"/api/documents/{doc_id}/ask", json={"question": QUESTION}, headers={"x-user-id": user})
        return d, a

    async with running() as c:
        d1, a1 = await ask(c, "u001")
        _, a2 = await ask(c, "u001")      # 同じ人が同じ質問をもう一度（登録は 200 で同じ文書）
        d3, a3 = await ask(c, "u002")     # 別の人が同じ PDF に同じ質問
        u1, u2 = await usage_of(c, "u001"), await usage_of(c, "u002")
    stats = await mock("GET", "/_mock/stats")
    base = {"answer": "肉じゃがは4人分です。", "citations": [{"page": 1, "quote": FIXTURE_QUOTE}]}

    def usage(i, o, made, read):
        return {"input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": made, "cache_read_input_tokens": read}

    eq((d1.status_code, d3.status_code), (201, 201), "登録")
    eq([a.headers.get("x-cache") for a in (a1, a2, a3)], ["miss", "hit", "miss"], f"x-cache（本文 {a1.text}）")
    eq(a1.json(), {**base, "usage": usage(12, 38, 4876, 0)}, "u001 の1回目")
    eq(a2.json(), {**base, "usage": usage(0, 0, 0, 0)}, "u001 の2回目")
    eq(a3.json(), {**base, "usage": usage(12, 38, 0, 4876)}, "u002 の1回目")
    eq((stats["total"], stats["by_scenario"]), (2, {"recipe_pdf_ask": 2}), "mockllm が受けた数")
    eq((u1["llm"], u1["response_cache"]), (usage(12, 38, 4876, 0), {"hits": 1, "misses": 1}), "u001 の利用量")
    eq((u2["llm"], u2["response_cache"]), (usage(12, 38, 0, 4876), {"hits": 0, "misses": 1}), "u002 の利用量")
    return "u001 miss（作成 4876）→ hit（LLM なし）・u002 miss（読み出し 4876）・mockllm total=2"


@check("V5 失敗した試行のトークンも記録し、失敗はキャッシュしない（502 → 200 miss → 200 hit）")
async def _():
    def result(confidence: float, out: int) -> ChatResult:
        items = [{"name": n, "quantity": "1個", "amount": 1, "unit": "個", "confidence": confidence, "category": "野菜"}
                 for n in ("キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳")]
        return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(1668, out))

    fake = FakeProvider([result(1.5, 120), result(1.5, 120), result(0.9, 194)])
    app.dependency_overrides[get_llm] = lambda: fake
    try:
        async with running() as c:
            rs = [await scan(c, "u005") for _ in range(3)]
            u = await usage_of(c, "u005")
    finally:
        app.dependency_overrides.clear()
    eq([r.status_code for r in rs], [502, 200, 200], "status")
    eq(rs[0].json()["error"]["type"], "invalid_output", "1回目の種別")
    eq([r.headers.get("x-cache") for r in rs[1:]], ["miss", "hit"], "x-cache")
    eq(len(fake.requests), 3, "LLM を呼んだ回数")
    eq((u["llm"]["input_tokens"], u["llm"]["output_tokens"], u["response_cache"]),
       (5004, 434, {"hits": 1, "misses": 2}), "利用量")
    return "502（2回分 3336/240 を記録）→ miss 1668/194 → hit・合計 5004/434・LLM 3 回"


class Probe:
    """音声認識の代わり。release が立つまで戻らず、同時にいくつ動いたかを数える。"""

    def __init__(self) -> None:
        self.calls = self.active = self.max_active = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, audio: np.ndarray, rate: int) -> stt.SttResult:
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.release.wait(timeout=30)
        finally:
            with self._lock:
                self.active -= 1
        return stt.SttResult("テスト", len(audio) / rate, 0.25)


@check("V6 音声認識に5件同時：同時1件・待ち2件まで受け付け、残り2件は 503 stt_busy（Retry-After: 2）")
async def _():
    wav = float32_to_wav(np.zeros(16000, np.float32), 16000)   # 1秒の無音
    probe = Probe()
    async with running() as c:
        app.state.transcriber = probe
        tasks = [asyncio.create_task(c.post("/api/voice/transcribe", files={"audio": ("a.wav", wav, "audio/wav")},
                                            headers={"x-user-id": "u002"})) for _ in range(5)]
        await settle(app.state.stt_gate, 5)
        probe.release.set()
        rs = await asyncio.gather(*tasks)
        u = await usage_of(c, "u002")
        stats = app.state.stt_gate.stats()
    eq(sorted(r.status_code for r in rs), [200, 200, 200, 503, 503], "status")
    err = next(r for r in rs if r.status_code == 503)
    eq((err.json()["error"]["type"], err.json()["error"]["message"], err.headers["retry-after"]),
       ("stt_busy", MSG_STT_BUSY, "2"), "503 の本文とヘッダ")
    eq((probe.calls, probe.max_active), (3, 1), "認識を呼んだ回数・同時に動いた最大数")
    eq((u["stt_seconds"], u["stt_processing_seconds"]), (3.0, 0.75), "利用量")
    eq((stats["running"], stats["waiting"], stats["rejected"]), (0, 0, 2), "入口の統計")
    return "200×3・503×2（stt_busy）・同時に動いた最大 1・stt_seconds 3.0・処理秒数 0.75"


class FakeVoicevox:
    """音声合成の代わり。release が立つまで戻らない。"""

    speaker = 3

    def __init__(self) -> None:
        self.calls = self.active = self.max_active = 0
        self.release = asyncio.Event()

    async def ensure_user_dict(self) -> int:
        return 0

    async def synthesize(self, text: str, *, sample_rate: int = 16000) -> TtsResult:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return TtsResult(float32_to_wav(np.zeros(sample_rate, np.float32), sample_rate), "", 1.0, 0.5)


@check("V7 音声合成に5件同時：同時1件・待ち3件まで受け付け、残り1件は 503 tts_busy。200 にはクレジットが付く")
async def _():
    fake = FakeVoicevox()
    async with running() as c:
        real, app.state.voicevox = app.state.voicevox, fake
        try:
            tasks = [asyncio.create_task(c.post("/api/voice/speak", json={"text": "鶏むね肉の塩炒めです。"},
                                                headers={"x-user-id": "u003"})) for _ in range(5)]
            await settle(app.state.tts_gate, 5)
            fake.release.set()
            rs = await asyncio.gather(*tasks)
            u = await usage_of(c, "u003")
        finally:
            app.state.voicevox = real
    eq(sorted(r.status_code for r in rs), [200, 200, 200, 200, 503], "status")
    err = next(r for r in rs if r.status_code == 503)
    eq((err.json()["error"]["type"], err.json()["error"]["message"]), ("tts_busy", MSG_TTS_BUSY), "503 の本文")
    ok = next(r for r in rs if r.status_code == 200)
    eq((ok.headers["content-type"], unquote(ok.headers["x-voice-credit"])), ("audio/wav", S.voicevox_credit), "200 のヘッダ")
    eq((fake.calls, fake.max_active), (4, 1), "合成を呼んだ回数・同時に動いた最大数")
    eq((u["tts_seconds"], u["tts_processing_seconds"]), (4.0, 2.0), "利用量")
    return f"200×4・503×1（tts_busy）・同時に動いた最大 1・クレジット {S.voicevox_credit}・tts_seconds 4.0"


@check("V8 ウォームアップ中は /health が 200・/health/deps が 503。終われば 200、失敗すれば 503 のまま")
async def _():
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow() -> None:
        entered.set()
        await release.wait()

    async def quick() -> None:
        return None

    async def broken() -> None:
        raise RuntimeError("起動できませんでした")

    async with running({"whisper": slow, "voicevox": quick}) as c:
        await entered.wait()
        live, before = await c.get("/health"), await c.get("/health/deps")
        release.set()
        await app.state.warmup.wait()
        after = await c.get("/health/deps")
    async with running({"whisper": quick, "voicevox": broken}) as c:
        await app.state.warmup.wait()
        failed = await c.get("/health/deps")
    eq((live.status_code, before.status_code, before.json()["warmup"]),
       (200, 503, {"whisper": "running", "voicevox": "pending"}), "ウォームアップ中")
    eq((after.status_code, after.json()["status"], after.json()["warmup"]),
       (200, "ok", {"whisper": "ok", "voicevox": "ok"}), "ウォームアップ後")
    eq((failed.status_code, failed.json()["warmup"]),
       (503, {"whisper": "ok", "voicevox": "ng (RuntimeError)"}), "失敗したとき")
    return "中：/health 200・/health/deps 503（running・pending）→ 後：200 → 失敗：503（ng (RuntimeError)）"


@check("V9 本物のウォームアップ（Whisper の読み込み＋1回の認識・VOICEVOX の辞書と1回の合成）が終わると 200")
async def _():
    async with running(None) as c:
        await app.state.warmup.wait()
        r = await c.get("/health/deps")
    body = r.json()
    eq((r.status_code, body["warmup"]), (200, {"whisper": "ok", "voicevox": "ok"}), f"readiness（本文 {body}）")
    eq([(g["running"], g["waiting"], g["rejected"]) for g in body["gates"].values()], [(0, 0, 0), (0, 0, 0)], "入口")
    return "warmup：whisper ok・voicevox ok・入口はどちらも空"


@check("V10 月の見積もり（pricing.yaml は仮の値）：LLM 31.06・命中率 20% で 24.85・サーバー 144.00・合計 175.06")
def _():
    p = est.load_pricing()
    eq((p["placeholder"], p["llm"]["input_per_mtok"], p["llm"]["output_per_mtok"]),
       (True, Decimal("1.0"), Decimal("5.0")), "単価表（仮の値）")
    e = est.estimate(est.Workload(), p)
    hit = est.estimate(replace(est.Workload(), response_cache_hit_rate=Decimal("0.2")), p)
    got = {k: (v if isinstance(v, int) else str(v)) for k, v in e.items()}
    eq(got, {"llm_input_tokens": 24_672_000, "llm_output_tokens": 1_278_000, "llm_input_cost": "24.67",
             "llm_output_cost": "6.39", "llm_cost": "31.06", "stt_seconds_per_day": "720.0",
             "tts_seconds_per_day": "1650.0", "processing_hours_per_month": "19.75", "peak_stt_percent": "6.0",
             "peak_tts_percent": "13.8", "server_cost": "144.00", "total_cost": "175.06"}, "見積もり")
    eq((hit["llm_input_tokens"], hit["llm_output_tokens"], str(hit["llm_cost"])),
       (19_737_600, 1_022_400, "24.85"), "命中率 20%")
    eq(est.report(est.Workload(), p)[0].startswith("※ pricing.yaml の単価は例示用の仮の値です"), True, "注意書き")
    return "入力 24,672,000・出力 1,278,000 → 31.06／命中率 20% → 24.85／STT 720.0 秒・TTS 1,650.0 秒/日／混む1時間 6.0%・13.8%"


@check("V11 保持時間（24時間）を過ぎた結果は使わない（時計を進めて確かめる）")
def _():
    clock = FixedClock()
    c = ResponseCache(clock, ttl_seconds=24 * 3600)
    c.put("k", "u001", {"v": 1}, Usage(1668, 194))
    clock.advance(timedelta(hours=23, minutes=59).total_seconds())
    first = c.get("k") is not None
    clock.advance(60)
    eq((first, c.get("k")), (True, None), "23時間59分後・24時間後")
    return "23時間59分後は命中・24時間後は期限切れ"


@check("V12 UsageBook.forget：利用者の横持ち（キャッシュの2項目・命中と外れ）を消し、他の利用者の分は残す")
def _():
    book = UsageBook(UsageLog(FixedClock()))
    for user in ("u001", "u002"):
        book.add_llm(user, "m", Usage(12, 38, cache_creation_input_tokens=4876))
        book.count_lookup(user, hit=False)
    book.forget("u001")
    eq((book._cache_tokens.get("u001"), book._lookups.get("u001")), (None, None), "u001 の横持ち")
    eq((book._cache_tokens["u002"]["cache_creation_input_tokens"], book._lookups["u002"]),
       (4876, {"hits": 0, "misses": 1}), "u002 の横持ち")
    return "u001 の作成 4876・外れ 1 を消す・u002 の作成 4876・外れ 1 は残る"


finish("session14")
