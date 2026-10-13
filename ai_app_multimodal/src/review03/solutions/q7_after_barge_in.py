"""問題7：割り込み（セッション11）のあとに、状態・会話履歴・利用量（セッション10）・LLM のストリームに何が残るかを、
本物の VoiceSession と決まったふるまいの偽物（時計・声の判定・認識・LLM・合成）で確かめる。

    docker compose exec api python -m src.review03.solutions.q7_after_barge_in
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from src.review03 import samples
from src.review03.asgi_ws import AsgiWebSocket
from src.review03.kit import LOOPBACK_TEXT, PLAYBACK_LEAD_S
from src.review03.solutions.q3_heard import history_text, state_path
from src.review03.testkit import (
    START, STOP, FakeVoicevox, FixedTranscriber, ManualClock, ScriptedProvider, chunks, fake_detector, labels, pattern,
    probe_app, receive_until, receive_until_audio, send_frames, swapped, wav_seconds,
)

TEXT2 = "豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。"
SECOND_REPLY = "わかりました、豚こま切れ肉で考えますね。"
SHORT_REPLY = "はい。塩炒めがおすすめです。"
FIRST = pattern((False, 300), (True, 900), (False, 720))     # 0.9 秒の発話（話し終わりの無音つき）
COUGH = pattern((True, 240), (False, 720))                   # 0.24 秒の咳
BARGE = pattern((True, 600), (False, 720))                   # 0.6 秒の発話（割り込み）

Steps = Callable[[AsgiWebSocket, list, ManualClock, list], Awaitable[None]]


async def until(ok: Callable[[], bool], timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while not ok():
            await asyncio.sleep(0.005)


async def while_speaking(ws, log, clock, sessions) -> None:
    """2文目を受け取った直後に、2文目をちょうど半分まで鳴らした時刻へ時計を進めて話しかける。"""
    await receive_until_audio(ws, log, 1)
    d0, d1 = [wav_seconds(m) for m in log if isinstance(m, bytes)]
    clock.t += PLAYBACK_LEAD_S + d0 + d1 / 2
    await send_frames(ws, chunks(BARGE))
    await receive_until(ws, log)


async def while_thinking(ws, log, clock, sessions) -> None:
    """返答の最初の文字（reply_delta）を受け取った直後に話しかける。まだ1文もできていない。"""
    await receive_until(ws, log, stop_types=("reply_delta",))
    await send_frames(ws, chunks(BARGE))
    await receive_until(ws, log)


async def cough_then_listen(ws, log, clock, sessions) -> None:
    """返答を送り終えたあと、鳴っている間に咳をする。そのあと鳴り終わる見込みの時刻を過ぎてから、無音を1つ送る。"""
    await receive_until(ws, log)
    await send_frames(ws, chunks(COUGH))
    await until(lambda: sessions[0].ignored == 1)      # 咳を捨てたのを見届けてから時計を進める
    clock.t += 60
    await send_frames(ws, [bytes(640)])


async def drive(scripts: list[tuple[str, int | None]], transcripts: tuple[str, ...], steps: Steps):
    clock = ManualClock()
    llm = ScriptedProvider(scripts)
    probe, sessions = probe_app(detector=fake_detector(), clock=clock)
    log: list = []
    async with probe.router.lifespan_context(probe):
        with swapped(probe.state, transcriber=FixedTranscriber(*transcripts), llm=llm, voicevox=FakeVoicevox()):
            async with AsgiWebSocket(probe) as ws:
                await ws.send_text(START)
                await send_frames(ws, chunks(FIRST))
                await steps(ws, log, clock, sessions)
                await ws.send_text(STOP)
                await receive_until(ws, log, stop_types=())
        records = list(probe.state.usage.records)
    return log, sessions[0], llm, records


def usage_text(records) -> str:
    return " ／ ".join(f"tts {r.audio_seconds} 秒" if r.kind == "tts" else r.kind for r in records)


async def run() -> None:
    reply = samples.kondate_reply()
    cases = [
        ("読み上げ中（2文目の途中）に話しかける",
         [(reply, reply.index("\n2.") + 1), (SECOND_REPLY, None)], (LOOPBACK_TEXT, TEXT2), while_speaking),
        ("考えている間（返答の文字の途中）に話しかける",
         [(reply, 12), (SECOND_REPLY, None)], (LOOPBACK_TEXT, TEXT2), while_thinking),
        ("咳をしただけで最後まで聞く",
         [(SHORT_REPLY, None)], (LOOPBACK_TEXT,), cough_then_listen),
    ]
    for label, scripts, transcripts, steps in cases:
        log, session, llm, records = await drive(scripts, transcripts, steps)
        print(f"{label}: {' → '.join(labels(log))}")
        print(f"  状態: {state_path(session.machine)}")
        print(f"  履歴: {history_text(session.history.messages)}・捨てた音 {session.ignored}")
        print(f"  利用量: {usage_text(records)}・ストリーム 途中で閉じた {llm.closed_early}・最後まで {llm.completed}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
