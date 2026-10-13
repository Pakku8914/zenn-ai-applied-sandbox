"""セッション11：練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session11

問題3はコードのない問題（ブラウザでの確認）なので検証しない。処理時間は合否に使わない。
"""

from __future__ import annotations

from kondate.verifykit import check, eq, finish
from src.session11.asgi_ws import AsgiWebSocket
from src.session11.session import VoiceSession
from src.session11.solutions.q1_turn_events import CASES as Q1_CASES
from src.session11.solutions.q1_turn_events import replay
from src.session11.solutions.q2_playback_gap import build, mismatch_windows
from src.session11.solutions.q4_thresholds import CASES as Q4_CASES
from src.session11.solutions.q4_thresholds import table, would_interrupt
from src.session11.solutions.q5_partial import S0, S1, demo, heard_with_partial
from src.session11.solutions.q6_swallow import bad_turn, good_turn, run
from src.session11.solutions.q7_stateful_threshold import StatefulThresholdSession
from src.session11.talk import START, STOP, chunks, receive_until, send_frames
from src.session11.testkit import (FakeVoicevox, FixedTranscriber, ManualClock, ScriptedProvider, fake_detector,
                                   labels, pattern, probe_app, swapped)

FIRST = pattern((False, 300), (True, 900), (False, 720))
HAI = pattern((True, 360), (False, 720))             # 「はい」程度の短い発話（0.36 秒）
KONDATE_HEAD = "鶏むね肉とキャベツがあるなら、"


@check("S1 出来事の列から状態の列を求め、起きないはずの出来事は ValueError")
def _():
    got = {}
    for name, events in Q1_CASES.items():
        try:
            got[name] = replay(events)
        except ValueError as e:
            got[name] = str(e)
    eq(got, {
        "A ふつうの1往復": ["listening", "thinking", "speaking", "listening"],
        "B 読み上げ中の割り込み": ["listening", "thinking", "speaking", "listening", "thinking", "speaking", "listening"],
        "C 考えている間の割り込み": ["listening", "thinking", "listening", "thinking", "listening"],
        "D 誤り": "thinking で playback_done は起きません",
    }, "状態の列")
    return "A 4 状態・B 7 状態（noise は何も変えない）・C 5 状態／D は ValueError"


@check("S2 再生の見積もりと、実際の再生が 1.0 秒遅れたときに食い違う時間帯")
def _():
    est = build(0.25)
    eq(est.ends, [8.75, 13.25, 18.75], "見積もりの鳴り終わり")
    eq([est.heard_count(t) for t in (8.0, 10.0, 14.0)], [0, 1, 2], "index")
    eq(build(1.0).ends, [9.5, 14.0, 19.5], "実際の鳴り終わり")
    eq(mismatch_windows(0.25, 1.0), [(8.75, 9.5), (13.25, 14.0), (18.75, 19.5)], "食い違う時間帯")
    return "index 0・1・2／食い違うのは 8.75〜9.5・13.25〜14.0・18.75〜19.5 秒"


@check("S4 しきい値ごとに、咳・物音・短い返事で止まるか")
def _():
    eq(table(), {
        "物音（120ms）": [False, False, False],
        "咳（240ms）": [True, False, False],
        "咳2回（210ms＋間300ms＋210ms）": [True, True, False],
        "「はい」（360ms）": [True, True, False],
        "「ちょっと待って」（750ms）": [True, True, True],
    }, "止まるか（150・300・500ms）")
    eq(would_interrupt(Q4_CASES["咳2回（210ms＋間300ms＋210ms）"], 300, consecutive=True), False, "続けて数える版")
    return "300ms：咳では止まらず「はい」では止まる／咳2回は足し算で届く（続けて数えれば止まらない）"


@check("S5 途中まで聞いた文を、時間の割合で切って残す")
def _():
    p = demo()
    eq(heard_with_partial(p, 6.0), ["鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの…"], "6 秒")
    eq(heard_with_partial(p, 10.0), [S0, "鶏むね肉をそぎ切りにして…"], "10 秒")
    eq(heard_with_partial(p, 12.0), [S0, S1], "12 秒（鳴り終えた）")
    return "6 秒：1文目の 35 文字＋…／10 秒：1文目＋「鶏むね肉をそぎ切りにして…」／12 秒：2文とも"


@check("S6 CancelledError を握りつぶすと、interrupted の前に turn_end が出て、取り消しが伝わらない")
async def _():
    bad, good = await run(bad_turn), await run(good_turn)
    eq((bad["sent"], bad["cancelled"], bad["closed"]),
       (["reply_delta:鶏むね肉とキ", "turn_end", "interrupted"], False, True), "握りつぶす")
    eq((good["sent"], good["cancelled"], good["closed"]),
       (["reply_delta:鶏むね肉とキ", "interrupted"], True, True), "伝える")
    return "握りつぶす：turn_end が出て cancelled() は False／伝える：interrupted だけで cancelled() は True"


async def converse(session_class: type[VoiceSession], scripts: list, in_thinking: bool) -> tuple[list, VoiceSession]:
    """1ターン目の途中（thinking か、読み上げを送り終えたあとの speaking）で「はい」と言う。"""
    llm = ScriptedProvider(scripts)
    probe, sessions = probe_app(session_class, detector=fake_detector(), clock=ManualClock())
    log: list = []
    async with probe.router.lifespan_context(probe):
        with swapped(probe.state, transcriber=FixedTranscriber("献立を考えて", "はい"), llm=llm,
                     voicevox=FakeVoicevox()):
            async with AsgiWebSocket(probe) as ws:
                await ws.send_text(START)
                await send_frames(ws, chunks(FIRST))
                await receive_until(ws, log, stop_types=("reply_delta",) if in_thinking else ("turn_end",))
                await send_frames(ws, chunks(HAI))
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
    return log, sessions[0]


@check("S7 読み上げ中だけしきい値を 500ms に上げると、0.36 秒の「はい」は読み上げ中には止めず、考えている間には止める")
async def _():
    speaking = [("はい、塩炒めにしましょう。", None), ("わかりました。", None)]
    thinking = [(KONDATE_HEAD, 3), ("わかりました。", None)]
    base_s, _ = await converse(VoiceSession, speaking, in_thinking=False)
    mine_s, mine_session = await converse(StatefulThresholdSession, speaking, in_thinking=False)
    head = ["ready", "vad:speech_start", "vad:speech_end", "transcript", "audio:0", "turn_end"]
    eq(labels(base_s), head + ["vad:speech_start", "interrupted:0", "vad:speech_end", "transcript", "audio:0",
                               "turn_end"], "元のセッション・読み上げ中")
    eq((labels(mine_s), mine_session.ignored), (head, 1), "状態で変える・読み上げ中")
    want = ["ready", "vad:speech_start", "vad:speech_end", "transcript", "vad:speech_start", "interrupted:0",
            "vad:speech_end", "transcript", "audio:0", "turn_end"]
    for cls in (VoiceSession, StatefulThresholdSession):
        log, session = await converse(cls, thinking, in_thinking=True)
        eq(labels(log), want, f"{cls.__name__}・考えている間")
        eq(session.history.messages[0]["content"], "献立を考えて\nはい", "まとめた user 発言")
    return "読み上げ中：元は止まる・状態で変える版は止まらない（捨てた音 1）／考えている間：どちらも止まる"


finish("session11-solutions")
