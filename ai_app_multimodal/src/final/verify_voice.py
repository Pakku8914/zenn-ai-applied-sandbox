"""最終プロジェクトの検証②：WS /ws/voice（同意・手元の食材・割り込み・入口・本物の部品での1ターン）。

    docker compose exec api bash verify-all.sh src/final

V1〜V3 は音声認識・音声合成・VAD を偽物に差し替えて決定的に確かめる。V4 だけが本物の VAD・Whisper・mockllm・VOICEVOX
を使う（1ターンと閉ループ検査。モデルの読み込みを含めて1分ほどかかる）。処理時間は合否に使わない。
"""

from __future__ import annotations

import json
from pathlib import Path

from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.media import media_path
from kondate.metrics import cer
from kondate.verifykit import check, eq, finish
from src.final.app import app
from src.final.asgi_ws import AsgiWebSocket
from src.final.gate import CpuGate
from src.final.history import INTERRUPTED_NOTE
from src.final.playback import PLAYBACK_LEAD_S
from src.final.sentences import split_sentences
from src.final.session import MSG_STT_BUSY
from src.final.talk import START, STOP, chunks, receive_until, receive_until_audio, send_frames, speech_pcm, utterance
from src.final.testkit import (OUT, TEXT, FakeVoicevox, FixedTranscriber, ManualClock, Observed, ScriptedProvider,
                               fake_detector, labels, mock, pattern, probe_app, running, swapped, voice_turn,
                               wav_seconds)

ROOT = Path(__file__).resolve().parents[2]
KONDATE = json.loads((ROOT / "mockllm/fixtures/kondate_chat.json").read_text(encoding="utf-8"))["steps"][0]["text"]
SENTENCES = split_sentences(KONDATE)
FRIDGE = media_path("fridge.jpg").read_bytes()
TEXT2 = "豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。"
SECOND_REPLY = "わかりました、豚こま切れ肉で考えますね。"
START_CONSENT = {"type": "start", "sample_rate": 16000, "store_audio": True}


@check("V1 写真を読んでから声で相談：手元の食材を system に添えても mockllm は kondate_chat。同意したので1発話を保存する")
async def _():
    await mock("POST", "/_mock/reset")
    out = OUT / "voice_v1"
    async with running(out=out) as c:
        await c.post("/api/fridge/scan", files={"image": ("fridge.jpg", FRIDGE)})
        observed = Observed(app.state.llm)
        fake = FakeVoicevox()
        with swapped(app.state, transcriber=FixedTranscriber(TEXT), voicevox=fake, make_detector=fake_detector,
                     llm=observed):
            log, code = await voice_turn(app, START_CONSENT)
        u = (await c.get("/api/usage")).json()
        voices = len(app.state.data.live("u001", "voice"))
    stats = await mock("GET", "/_mock/stats")
    req = observed.requests[0]
    eq(log[0], {"type": "ready", "credit": "VOICEVOX:ずんだもん", "store_audio": True}, "ready")
    eq(labels(log), ["ready", "vad:speech_start", "vad:speech_end", "transcript",
                     *[f"audio:{i}" for i in range(len(SENTENCES))], "turn_end"], "メッセージの順")
    eq([m["text"] for m in log if isinstance(m, dict) and m["type"] == "audio"], SENTENCES, "読み上げた文")
    eq((req.messages, "利用者の手元にある食材：キャベツ、鶏むね肉、卵、にんじん、牛乳。" in req.system),
       ([{"role": "user", "content": TEXT}], True), "LLM に渡したもの")
    eq(stats["by_scenario"], {"fridge_photo": 1, "kondate_chat": 1}, "mockllm のシナリオ")
    end = next(m for m in log if isinstance(m, dict) and m["type"] == "turn_end")
    eq(all(isinstance(v, int) for v in end["latency_ms"].values()), True, "latency_ms の5項目")
    eq((voices, len(list((out / "voice").glob("vc_*.wav"))), code), (1, 1, 1000), "保存した音声・close コード")
    tts = round(sum(round(len(s) * 0.125 * 24000) / 24000 for s in SENTENCES), 3)
    eq((u["stt_seconds"], u["tts_seconds"], u["llm"]["input_tokens"] > 0), (1.8, tts, True), "利用量")
    return (f"ready（store_audio true）→ transcript → audio 0〜{len(SENTENCES) - 1} → turn_end／"
            "system に手元の食材5品・シナリオは kondate_chat／保存 1件／stt_seconds 1.8")


@check("V2 割り込み：2文目の途中で話しかけると interrupted(index 1)、次のターンの履歴は聞かせた1文＋印")
async def _():
    clock = ManualClock()
    llm = ScriptedProvider([(KONDATE, KONDATE.index("\n2.") + 1), (SECOND_REPLY, None)])
    probe, sessions = probe_app(detector=fake_detector(), clock=clock)
    log: list = []
    async with probe.router.lifespan_context(probe):
        with swapped(probe.state, transcriber=FixedTranscriber(TEXT, TEXT2), llm=llm, voicevox=FakeVoicevox()):
            async with AsgiWebSocket(probe) as ws:
                await ws.send_text(START)
                await send_frames(ws, chunks(pattern((False, 300), (True, 900), (False, 720))))
                await receive_until_audio(ws, log, 1)
                d0, d1 = [wav_seconds(m) for m in log if isinstance(m, bytes)]
                clock.t += PLAYBACK_LEAD_S + d0 + d1 / 2
                noise = pattern((True, 90), (False, 750))
                cough = pattern((True, 240), (False, 720))
                barge = pattern((True, 600), (False, 720))
                await send_frames(ws, chunks(noise + cough + barge))
                await receive_until(ws, log)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
    session = sessions[0]
    eq(labels(log), ["ready", "vad:speech_start", "vad:speech_end", "transcript", "audio:0", "audio:1",
                     "vad:speech_start", "interrupted:1", "vad:speech_end", "transcript", "audio:0", "turn_end"],
       "メッセージの順")
    eq((session.ignored, llm.closed_early, llm.completed), (1, 1, 1), "捨てた音・LLM のストリーム")
    eq(llm.requests[1].messages, [
        {"role": "user", "content": TEXT},
        {"role": "assistant", "content": SENTENCES[0] + "\n" + INTERRUPTED_NOTE},
        {"role": "user", "content": TEXT2},
    ], "次のターンに渡した履歴")
    eq(ws.close_code, 1000, "close コード")
    return "audio 0・1 → speech_start → interrupted(1) → 次のターン／咳では止まらない（捨てた音 1）／履歴は1文＋印"


@check("V3 音声認識の入口があふれていたら、ターンは error {type: stt_busy} で終わり、listening に戻る")
async def _():
    full = CpuGate("stt", 1, 2)
    full.inflight = 3                                   # 動いている1件＋待っている2件で、もう入れない
    async with running():
        with swapped(app.state, stt_gate=full, transcriber=FixedTranscriber(TEXT), voicevox=FakeVoicevox(),
                     make_detector=fake_detector, llm=FakeProvider([ChatResult("はい。", [], "end_turn", Usage(1, 1))])):
            log, code = await voice_turn(app, {"type": "start", "sample_rate": 16000})
    errors = [m["error"] for m in log if isinstance(m, dict) and m["type"] == "error"]
    eq(labels(log), ["ready", "vad:speech_start", "vad:speech_end", "error"], "メッセージの順")
    eq((errors[0]["type"], errors[0]["message"], code, full.rejected), ("stt_busy", MSG_STT_BUSY, 1000, 1), "error の中身")
    eq(log[0]["store_audio"], False, "store_audio を送らなければ保存しない")
    return "ready（store_audio false）→ vad → error {stt_busy}（turn_end なし）→ stop で 1000"


@check("V4 本物の部品で1ターン（VAD・Whisper・mockllm・VOICEVOX）と、閉ループ検査 POST /api/voice/loopback")
async def _():
    pcm = await speech_pcm(TEXT)
    log: list = []
    async with running() as c:
        loop = await c.post("/api/voice/loopback")
        async with AsgiWebSocket(app) as ws:
            await ws.send_text(START)
            await send_frames(ws, utterance(pcm))
            await receive_until(ws, log)
            await ws.send_text(STOP)
            await receive_until(ws, log, stop_types=())
        u = (await c.get("/api/usage")).json()
    body = loop.json()
    eq((loop.status_code, body["passed"], body["credit"]), (200, True, "VOICEVOX:ずんだもん"), f"閉ループ（本文 {body}）")
    got = labels(log)
    eq((got[:4], got.count("audio:0"), got[-1], ws.close_code),
       (["ready", "vad:speech_start", "vad:speech_end", "transcript"], 1, "turn_end", 1000), "メッセージの順")
    text = next(m["text"] for m in log if isinstance(m, dict) and m["type"] == "transcript")
    assert cer(TEXT, text) <= 0.10, text
    lat = next(m for m in log if isinstance(m, dict) and m["type"] == "turn_end")["latency_ms"]
    parts = lat["vad"] + lat["stt"] + lat["llm_first_sentence"] + lat["tts_first"]
    eq(lat["first_audio"] >= parts - 2, True, f"first_audio は4つの和以上（{lat}）")
    eq((u["stt_seconds"] > 0, u["tts_seconds"] > 0, u["llm"]["input_tokens"] > 0), (True, True, True), "利用量")
    return "閉ループ passed／transcript の CER 0.10 以下 → audio → turn_end（first_audio ≥ 内訳の和）／利用量に STT・TTS・LLM"


finish("final-voice")
