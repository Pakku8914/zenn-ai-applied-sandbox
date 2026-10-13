"""セッション8の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session08

処理時間・RTF は合否に使わない（表示もしない）。合否はサンプル数・秒数・CER・HTTP ステータス・呼び出し回数で決める。
Whisper は small（キャッシュ済み）だけを使う。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx2
import numpy as np

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.metrics import cer, normalize_ja
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.verifykit import check, eq, finish
from src.session08 import compare
from src.session08.app import app
from src.session08.audio_in import to_16k_mono
from src.session08.loopback_check import CASES, judge, run_cases
from src.session08.phrases import LOOPBACK_TEXT, SENTENCES
from src.session08.testaudio import tone_wav
from src.session08.textnorm import cer_relaxed

S = get_settings()
PATH = "/api/voice/transcribe"


@asynccontextmanager
async def running(application) -> AsyncIterator[httpx2.AsyncClient]:
    """lifespan を動かしてから ASGITransport でアプリに直接投げる（api コンテナの APP_MODULE を切り替えなくてよい）。"""
    async with application.router.lifespan_context(application):
        transport = httpx2.ASGITransport(app=application)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
            yield client


class Probe:
    """認識の代わりに呼ばれ、呼ばれた回数と「同時にいくつ動いていたか」を数える（時間ではなく回数で判定する）。"""

    def __init__(self, hold: float = 0.0, barrier: threading.Barrier | None = None) -> None:
        self.calls = self.active = self.max_active = 0
        self.hold, self.barrier = hold, barrier
        self._lock = threading.Lock()

    def __call__(self, audio: np.ndarray, rate: int) -> stt.SttResult:
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.barrier:
                self.barrier.wait(timeout=10)
            time.sleep(self.hold)
        finally:
            with self._lock:
                self.active -= 1
        return stt.SttResult("テスト", len(audio) / rate, 0.0)


@check("V1 WAV を 16kHz・モノラルに変換したサンプル数と秒数")
def _():
    cases = [(48000, 2, 1.0), (24000, 1, 2.5), (44100, 2, 1.0), (16000, 1, 1.0)]
    got = []
    for rate, ch, sec in cases:
        audio, r = wav_to_float32(tone_wav(rate, sec, channels=ch))
        out = to_16k_mono(audio, r)
        got.append((r, ch, len(out), len(out) / 16000))
    eq(got, [(48000, 2, 16000, 1.0), (24000, 1, 40000, 2.5), (44100, 2, 16000, 1.0), (16000, 1, 16000, 1.0)], "変換後")
    return "48kHz×2ch 1秒→16000・24kHz 2.5秒→40000・44.1kHz×2ch 1秒→16000・16kHz→そのまま"


@check("V2 24kHz の音声を 16kHz と偽ると長さが 1.5 倍になり、stt.transcribe はレート違いを断る")
def _():
    audio, rate = wav_to_float32(tone_wav(24000, 1.0))
    eq(len(audio) / 16000, 1.5, "16kHz と偽ったときの秒数")
    try:
        stt.transcribe(audio, rate)
    except ValueError as e:
        return str(e)
    raise AssertionError("ValueError にならなかった")


@check("V3 CER の正規化と表記ゆれの吸収（計算例）")
def _():
    eq(normalize_ja("ｷｬﾍﾞﾂ２個、ください！"), "キャベツ2個ください", "NFKC と句読点")
    pairs = [
        ("冷蔵庫に卵と牛乳とにんじんがあります。", "冷蔵庫に卵と牛乳とニンジンがあります", 0.2222, 0.0),
        ("小麦を使わない晩ごはんを探して。", "小麦を使わない番模範を探して", 0.2667, 0.2667),
        (LOOPBACK_TEXT, "ニワトリ胸肉とキャベツで20分で作れる料理は", 0.25, 0.2),
    ]
    got = [(round(cer(r, h), 4), round(cer_relaxed(r, h), 4)) for r, h, _, _ in pairs]
    eq(got, [(s, x) for _, _, s, x in pairs], "厳密・ゆれ吸収")
    return "にんじん 0.2222→0.0・晩ごはん 0.2667→0.2667・ニワトリ 0.25→0.2"


@check("V4 受付の検査：大きすぎ 413・WAV でない 415・中身が足りない 422（認識は呼ばれない）")
async def _():
    probe = Probe()
    got = []
    async with running(app) as client:
        app.state.transcriber = probe

        async def post(field: str, data: bytes) -> tuple[int, str]:
            r = await client.post(PATH, files={field: ("a.wav", data, "audio/wav")})
            return r.status_code, r.json()["error"]["type"]

        got.append(await post("audio", b"RIFF\x00\x00\x00\x00WAVE" + bytes(S.upload_max_bytes)))  # 10MB 超
        got.append(await post("audio", tone_wav(16000, 61.0)))                                   # 61 秒
        got.append(await post("audio", b"\x89PNG\r\n\x1a\n" + bytes(100)))                       # PNG
        got.append(await post("audio", tone_wav(16000, 1.0, sampwidth=1)))                       # 8bit の WAV
        got.append(await post("audio", tone_wav(16000, 0.05)))                                   # 0.05 秒
        got.append(await post("file", tone_wav(16000, 1.0)))                                     # 項目名の間違い
    eq(got, [(413, "too_large"), (413, "too_large"), (415, "unsupported_media"), (415, "unsupported_media"),
             (422, "invalid_request"), (422, "invalid_request")], "ステータスと種別")
    eq(probe.calls, 0, "認識を呼んだ回数")
    return "413×2・415×2・422×2・認識の呼び出し 0 回"


@check("V5 同時に3件送っても、limiter（同時1件）で認識は1件ずつ動く。limiter なしだと3件が同時に動く")
async def _():
    wav = tone_wav(16000, 1.0)
    async with running(app) as client:
        good = Probe(hold=0.2)
        app.state.transcriber = good
        rs = await asyncio.gather(*(client.post(PATH, files={"audio": ("a.wav", wav, "audio/wav")}) for _ in range(3)))
    eq([r.status_code for r in rs], [200, 200, 200], "status")
    eq((good.calls, good.max_active), (3, 1), "呼ばれた回数・同時に動いた最大数")

    bad = Probe(barrier=threading.Barrier(3))      # 3件が同時にここへ来ないと先へ進めない（来なければ10秒で失敗）

    async def call() -> None:
        await anyio.to_thread.run_sync(bad, np.zeros(16000, np.float32), 16000)   # limiter を渡さない

    await asyncio.gather(*(call() for _ in range(3)))
    eq(bad.max_active, 3, "limiter なしの同時実行数")
    return "limiter あり 最大1件・なし 最大3件"


@check("V6 VOICEVOX の 24kHz の WAV を送ると、16kHz に変換して認識し、CER が 0.10 以下")
async def _():
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        tts = await vv.synthesize(LOOPBACK_TEXT, sample_rate=24000)
    finally:
        await vv.aclose()
    audio24, rate = wav_to_float32(tts.wav)
    eq(rate, 24000, "VOICEVOX の出力レート")
    n16 = len(to_16k_mono(audio24, rate))
    eq(n16, round(len(audio24) * 16000 / 24000), "16kHz にしたサンプル数")

    async with running(app) as client:
        r = await client.post(PATH, files={"audio": ("q.wav", tts.wav, "audio/wav")}, headers={"x-user-id": "u002"})
        records = list(app.state.usage.records)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    eq(sorted(body), ["audio_seconds", "rtf", "text"], "項目")
    eq(body["audio_seconds"], round(n16 / 16000, 2), "audio_seconds")
    score = cer(LOOPBACK_TEXT, body["text"])
    assert score <= 0.10, (score, body["text"])
    eq([(x.user_id, x.kind, x.model) for x in records], [("u002", "stt", f"whisper:{S.whisper_model}")], "利用量の記録")
    return f"audio_seconds={body['audio_seconds']}・CER ≤ 0.10・利用量 1 件（u002・stt・whisper:{S.whisper_model}）"


@check("V7 10文の閉ループ（small・int8・beam 1・2 スレッド）で、全体の CER が 0.15 以下・1文目が 0.10 以下")
def _():
    clips = asyncio.run(compare.synthesize_all(SENTENCES))
    row = compare.evaluate(clips, SENTENCES, "small", compute_type="int8", beam=1, threads=2)
    assert row.cer <= 0.15, row
    assert row.cer_relaxed <= row.cer, row
    first = cer(SENTENCES[0], row.transcripts[0])
    assert first <= 0.10, (first, row.transcripts[0])
    return "10文の CER ≤ 0.15・ゆれ吸収 ≤ 厳密・1文目 ≤ 0.10"


@check("V8 閉ループの回帰テスト：辞書が外れたときの聞き取りを FAIL にでき、いまの環境では全件 PASS")
def _():
    nodict = judge(CASES[0], "ニワトリ胸肉とキャベツで20分で作れる料理は")
    eq((nodict.score, nodict.passed), (0.25, False), "辞書なしの聞き取り")
    outcomes = asyncio.run(run_cases(CASES))
    eq([o.passed for o in outcomes], [True] * len(CASES), f"判定（{[(o.transcript, o.score) for o in outcomes]}）")
    return f"辞書なし CER 0.25 → FAIL・いまの環境 {len(CASES)}/{len(CASES)} PASS"


finish("session08")
