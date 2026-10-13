"""セッション11の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session11

合否は、メッセージの順番・interrupted の index・履歴の中身・状態の移り変わり・取り消した数で決める。
処理時間は合否に使わない（表示もしない）。「2文目の途中」は、時間ではなく「audio 1 とその WAV を受け取った直後」で決め、
どこまで聞かせたかの見積もりに使う時計は、検証が動かすまで止まっている時計（ManualClock）に差し替える。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
from anthropic import AsyncAnthropic

from kondate.llm import AnthropicProvider, ChatResult, FakeProvider, Usage
from kondate.metrics import cer
from kondate.verifykit import check, eq, finish
from src.session11.app import app
from src.session11.asgi_ws import AsgiWebSocket
from src.session11.history import INTERRUPTED_NOTE, Conversation
from src.session11.playback import PLAYBACK_LEAD_S, PlaybackEstimate
from src.session11.talk import (START, STOP, chunks, receive_until, receive_until_audio, send_frames, speech_pcm,
                                utterance)
from src.session11.testkit import (FixedTranscriber, ManualClock, Observed, ScriptedProvider, fake_detector, labels,
                                   pattern, probe_app, swapped, wav_seconds)
from src.session11.turns import TurnMachine, TurnState
from src.session11.vad import UtteranceDetector

ROOT = Path(__file__).resolve().parents[2]
TEXT1 = "鶏むね肉とキャベツで20分で作れる料理は？"
TEXT2 = "豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。"
SECOND_REPLY = "わかりました、豚こま切れ肉で考えますね。"
EXPECTED = [
    "鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。",
    "鶏むね肉をそぎ切りにして、片栗粉を薄くまぶします。",
]
KONDATE = json.loads((ROOT / "mockllm/fixtures/kondate_chat.json").read_text(encoding="utf-8"))["steps"][0]["text"]
FIRST = pattern((False, 300), (True, 900), (False, 720))     # 0.9 秒の発話（話し終わりの無音つき）
NOISE = pattern((True, 90), (False, 750))                    # 0.09 秒の雑音
COUGH = pattern((True, 240), (False, 720))                   # 0.24 秒の咳
BARGE = pattern((True, 600), (False, 720))                   # 0.6 秒の発話（割り込み）
L, T, S = TurnState.LISTENING, TurnState.THINKING, TurnState.SPEAKING
_pcm_cache: dict[str, bytes] = {}


async def speech(text: str) -> bytes:
    if text not in _pcm_cache:
        _pcm_cache[text] = await speech_pcm(text)
    return _pcm_cache[text]


@check("V1 ターンの状態機械：listening → thinking → speaking → listening の表にある移り方だけを許す")
def _():
    m = TurnMachine()
    for state, why in [(T, "speech_end"), (S, "first_audio"), (L, "barge_in"), (T, "speech_end"), (L, "no_reply")]:
        m.to(state, why)
    eq([s for s, _ in m.log], ["listening", "thinking", "speaking", "listening", "thinking", "listening"], "状態の列")
    rejected = []
    for path, target in [([], S), ([], L), ([T, S], T)]:
        mm = TurnMachine()
        for state in path:
            mm.to(state, "test")
        try:
            mm.to(target, "test")
            rejected.append(False)
        except ValueError:
            rejected.append(True)
    eq(rejected, [True, True, True], "表に無い移り方")
    return "listening→thinking→speaking→listening→thinking→listening／listening→speaking・listening→listening・speaking→thinking は ValueError"


@check("V2 再生の見積もり：鳴り始め＝max(送った時刻＋lead, 前の文の鳴り終わり)")
def _():
    p = PlaybackEstimate(lead_s=0.5)
    p.add("A", 2.0, 10.0)
    p.add("B", 1.25, 11.0)
    p.add("C", 3.0, 20.0)
    eq(p.ends, [12.5, 13.75, 23.5], "鳴り終わりの見積もり")
    eq([p.heard_count(x) for x in (12.0, 12.5, 15.0, 23.5)], [0, 1, 2, 3], "聞き終えた文の数")
    eq((p.heard(13.75), p.finished(23.0), p.finished(23.5)), (["A", "B"], False, True), "聞いた文と鳴り終わり")
    eq(PLAYBACK_LEAD_S, 0.3, "本文の lead")
    return "鳴り終わり 12.5・13.75・23.5 秒／12.0 秒で 0 文・12.5 秒で 1 文・15.0 秒で 2 文・23.5 秒で 3 文"


@check("V3 会話履歴：割り込まれた返答は聞かせた文＋印、返答の前の割り込みは user をまとめる")
def _():
    c = Conversation()
    c.add_user("鶏むね肉で何か作れる？")
    c.add_assistant(["塩炒めがおすすめです。"], interrupted=True)
    c.add_user("豚肉ならどう？")
    c.add_user("4人分で。")                      # 返事を聞く前に言い足した
    c.add_assistant([], interrupted=True)        # 1文目の途中で止めた
    c.add_assistant([], interrupted=False)       # 何も送らなかった：残さない
    snap = c.snapshot()
    eq(snap, [
        {"role": "user", "content": "鶏むね肉で何か作れる？"},
        {"role": "assistant", "content": "塩炒めがおすすめです。\n" + INTERRUPTED_NOTE},
        {"role": "user", "content": "豚肉ならどう？\n4人分で。"},
        {"role": "assistant", "content": INTERRUPTED_NOTE},
    ], "履歴")
    c.add_user("あと1品。")
    eq(len(snap), 4, "渡した写しは、あとから履歴が伸びても変わらない")
    return "user・assistant（1文＋印）・user（2つをまとめる）・assistant（印だけ）／写しは変わらない"


@check("V4 割り込みの判定に使う「この発話の声ありの長さ」を数える")
async def _():
    det = fake_detector()
    det.push(pattern((False, 300), (True, 90), (False, 750)))
    eq((det.in_speech, det.voiced_frames), (False, 0), "0.09 秒の声")
    det = fake_detector()
    det.push(pattern((True, 240)))
    eq((det.in_speech, det.voiced_frames), (True, 8), "0.24 秒の声")
    det.push(pattern((True, 60)))
    eq(det.voiced_frames, 10, "さらに 60ms")
    real, peak, events = UtteranceDetector(), 0, []
    for c in utterance(await speech(TEXT2)):
        events += [e.kind for e in real.push(c)]
        if real.in_speech:
            peak = max(peak, real.voiced_frames)
    eq((events, peak >= 10), (["speech_start", "speech_end"], True), "webrtcvad と合成した発話")
    return "0.09 秒 → 話し始めず 0／0.24 秒 → 8 フレーム（240ms）／さらに 60ms → 10 フレーム（300ms）／合成した発話は 300ms に届く"


@check("V5 読み上げの2文目の途中で話しかけると、作りかけの返答を取り消し、聞かせた文までを履歴に残す")
async def _():
    clock = ManualClock()
    llm = ScriptedProvider([(KONDATE, KONDATE.index("\n2.") + 1), (SECOND_REPLY, None)])  # 2文目まで流して止まる
    probe, sessions = probe_app(detector=fake_detector(), clock=clock)
    log: list = []
    async with probe.router.lifespan_context(probe):
        with swapped(probe.state, transcriber=FixedTranscriber(TEXT1, TEXT2), llm=llm):
            async with AsgiWebSocket(probe) as ws:
                await ws.send_text(START)
                await send_frames(ws, chunks(FIRST))
                await receive_until_audio(ws, log, 1)
                d0, d1 = [wav_seconds(m) for m in log if isinstance(m, bytes)]
                clock.t += PLAYBACK_LEAD_S + d0 + d1 / 2     # 2文目をちょうど半分まで鳴らした時刻
                await send_frames(ws, chunks(NOISE + COUGH + BARGE))
                await receive_until(ws, log)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
    session = sessions[0]
    eq(labels(log), ["ready", "vad:speech_start", "vad:speech_end", "transcript", "audio:0", "audio:1",
                     "vad:speech_start", "interrupted:1", "vad:speech_end", "transcript", "audio:0", "turn_end"],
       "メッセージの順")
    eq([m["text"] for m in log if isinstance(m, dict) and m["type"] == "audio"][:2], EXPECTED, "読み上げた2文")
    eq(session.ignored, 1, "割り込みに届かずに捨てた音")
    eq((llm.closed_early, llm.completed), (1, 1), "LLM のストリーム（途中で閉じた・最後まで流した）")
    eq(llm.requests[1].messages, [
        {"role": "user", "content": TEXT1},
        {"role": "assistant", "content": EXPECTED[0] + "\n" + INTERRUPTED_NOTE},
        {"role": "user", "content": TEXT2},
    ], "次のターンに渡した履歴")
    eq(session.machine.log, [("listening", "connect"), ("thinking", "speech_end"), ("speaking", "first_audio"),
                             ("listening", "barge_in"), ("thinking", "speech_end"), ("speaking", "first_audio")],
       "状態の移り変わり")
    eq(ws.close_code, 1000, "stop のあとの close コード")
    return ("audio 0・1 → vad(speech_start) → interrupted(index 1) → 次のターン（transcript・audio 0・turn_end）／"
            "0.09 秒の音と 0.24 秒の咳では止まらない（捨てた音 1）／次の履歴は user・assistant（1文＋印）・user")


@check("V6 考えている間（LLM のストリームの途中）に話しかけると、mockllm への接続を閉じ、2つの発言を1つにまとめる")
async def _():
    slow = AsyncAnthropic(max_retries=0, default_headers={"x-mock-tps": "2"})   # 差分ごとに 3 秒待たせる
    llm = Observed(AnthropicProvider(slow), FakeProvider([ChatResult(SECOND_REPLY, [], "end_turn", Usage(1, 1))]))
    probe, sessions = probe_app(detector=fake_detector())
    log: list = []
    try:
        async with probe.router.lifespan_context(probe):
            with swapped(probe.state, transcriber=FixedTranscriber(TEXT1, TEXT2), llm=llm):
                async with AsgiWebSocket(probe) as ws:
                    await ws.send_text(START)
                    await send_frames(ws, chunks(FIRST))
                    await receive_until(ws, log, stop_types=("reply_delta",))
                    await send_frames(ws, chunks(BARGE))
                    await receive_until(ws, log)
                    await ws.send_text(STOP)
                    await receive_until(ws, log, stop_types=())
    finally:
        await slow.close()
    session = sessions[0]
    eq(labels(log), ["ready", "vad:speech_start", "vad:speech_end", "transcript", "vad:speech_start", "interrupted:0",
                     "vad:speech_end", "transcript", "audio:0", "turn_end"], "メッセージの順")
    eq((llm.closed_early, llm.completed), (1, 1), "mockllm のストリームを途中で閉じた")
    eq(llm.requests[1].messages, [{"role": "user", "content": TEXT1 + "\n" + TEXT2}], "次のターンに渡した履歴")
    eq(session.machine.log, [("listening", "connect"), ("thinking", "speech_end"), ("listening", "barge_in"),
                             ("thinking", "speech_end"), ("speaking", "first_audio")], "状態の移り変わり")
    return "reply_delta の途中で interrupted(index 0)／ストリームを閉じた 1／次の履歴は user 1件（2つの発言をまとめる）"


@check("V7 GET / の画面は、エコー除去を求め、interrupted で再生を止める")
async def _():
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
            page = await client.get("/")
            worklet = await client.get("/static/pcm-worklet.js")
    eq((page.status_code, worklet.status_code), (200, 200), "GET / と worklet")
    needles = ["echoCancellation: ECHO", "noiseSuppression: ECHO", 'case "interrupted"', "stopPlayback()",
               "getSettings()", "/ws/voice"]
    eq([n for n in needles if n not in page.text], [], "画面に必要な記述")
    return "GET / 200（echoCancellation・noiseSuppression・interrupted で stopPlayback）／worklet 200"


@check("V8 本物の VAD・音声認識・mockllm・VOICEVOX でも、2文目を受け取った直後の発話で割り込み、次のターンに進む")
async def _():
    first, second = utterance(await speech(TEXT1)), utterance(await speech(TEXT2))
    log: list = []
    async with app.router.lifespan_context(app):
        observed = Observed(app.state.llm)
        with swapped(app.state, llm=observed):
            async with AsgiWebSocket(app) as ws:
                await ws.send_text(START)
                await send_frames(ws, first)
                await receive_until_audio(ws, log, 1)
                await send_frames(ws, second)
                await receive_until(ws, log)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
    got = labels(log)
    cut = next(i for i, x in enumerate(got) if x.startswith("interrupted:"))
    before, after = got[:cut], got[cut + 1:]
    eq(before[:4], ["ready", "vad:speech_start", "vad:speech_end", "transcript"], "最初の4通")
    eq([x for x in before if x.startswith("audio:")][:2], ["audio:0", "audio:1"], "割り込みの前の audio")
    eq(before[-1], "vad:speech_start", "interrupted の直前")
    index = int(got[cut].split(":")[1])
    assert index in (0, 1), got[cut]                 # 実時間の見積もり：1文目（約 8.5 秒）を鳴らしている途中なら 0
    eq(after[:2], ["vad:speech_end", "transcript"], "割り込みのあと")
    eq((after.count("audio:0"), after[-1], ws.close_code), (1, "turn_end", 1000), "次のターンと close コード")
    texts = [m["text"] for m in log if isinstance(m, dict) and m["type"] == "transcript"]
    assert cer(TEXT1, texts[0]) <= 0.10 and cer(TEXT2, texts[1]) <= 0.25, texts
    msgs = observed.requests[1].messages
    eq(([m["role"] for m in msgs], msgs[1]["content"].endswith(INTERRUPTED_NOTE)),
       (["user", "assistant", "user"], True), "次のリクエストの履歴")
    return ("audio 0・1 のあとの発話で speech_start → interrupted（index は 0 か 1）→ 次のターン → turn_end／"
            "次のリクエストは user・assistant（割り込みの印つき）・user")


finish("session11")
