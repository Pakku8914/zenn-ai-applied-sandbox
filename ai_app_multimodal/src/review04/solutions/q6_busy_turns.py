"""問題6：混んだ音声認識の入口（S14）と、ターンの状態（S11）・遅延の内訳（S10）・文ごとの読み上げ（S9）。

    docker compose exec api python -m src.review04.solutions.q6_busy_turns

音声認識は「Event が立つまで戻らない」差し替えで動かし、時間ではなく順番で確かめる（処理時間は測らない）。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from src.review04.kit import Busy, CpuGate, TurnMachine, TurnState, split_sentences

STT_SECONDS = Decimal("2.4")   # 1発話 4 秒 × RTF 0.6（セッション14の計算）
REPLY = (
    "## 鶏むね肉とキャベツの塩炒め\n"
    "1. キャベツをざく切りにします。\n"
    "2. 鶏むね肉を**一口大**に切って炒めます。\n"
    "3. 塩で味を調えたら完成です！"
)


class Recognizer:
    """音声認識の代わり。頼まれた名前ごとの Event が立つまで戻らず、同時に動いた数を数える。"""

    def __init__(self) -> None:
        self.events: dict[str, asyncio.Event] = {}
        self.active = self.max_active = self.done = 0

    def job(self, name: str):
        event = self.events[name] = asyncio.Event()

        async def recognize() -> str:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await event.wait()
            finally:
                self.active -= 1
            self.done += 1
            return f"{name} の発話"

        return recognize


class Voice:
    """1本の WebSocket 接続：ターンの状態と、クライアントに送ったメッセージ。"""

    def __init__(self) -> None:
        self.turns = TurnMachine()
        self.sent: list[str] = []


async def speech_end(gate: CpuGate, rec: Recognizer, v: Voice, job: str) -> tuple[asyncio.Task | None, str]:
    """話し終わり。入口に認識を頼み、受け付けられたら (task, 説明)、あふれたら error を送って listening に戻す。"""
    v.turns.to(TurnState.THINKING, "speech_end")
    v.sent.append("vad(speech_end)")
    ahead = gate.inflight                       # 自分より前にいる数（動いている＋待っている）
    task = asyncio.create_task(gate.run(rec.job(job)))
    await asyncio.sleep(0)                      # 入口の判定（_admit）は最初の一歩で済む
    if task.done() and isinstance(task.exception(), Busy):
        v.sent.append("error(stt_busy)")
        v.turns.to(TurnState.LISTENING, "no_reply")
        return None, "503 stt_busy"
    return task, f"受付（前に {ahead} 件）"


async def recognized(rec: Recognizer, v: Voice, task: asyncio.Task, job: str) -> None:
    """認識が終わる → 返答を読み上げる → 鳴り終わる（読み上げの中身はこの問題では扱わない）。"""
    rec.events[job].set()
    await task
    v.turns.to(TurnState.SPEAKING, "first_audio")


def path(m: TurnMachine) -> str:
    return m.log[0][0] + "".join(f" → {state}({reason})" for state, reason in m.log[1:])


async def simulate() -> list[str]:
    gate = CpuGate("stt", concurrency=1, max_waiting=2)       # セッション14の STT の入口
    rec = Recognizer()
    v = {name: Voice() for name in "ABCD"}
    tasks: dict[str, asyncio.Task] = {}
    upper: dict[str, Decimal] = {}

    async def finish(name: str, job: str) -> str:
        ahead = gate.inflight
        task, how = await speech_end(gate, rec, v[name], job)
        if task is not None:
            tasks[job] = task
            upper[job] = (ahead + 1) * STT_SECONDS             # 前の全員＋自分の処理（いちばん長い場合）
        return how

    lines = ["1. 4人が同時に話し終える：" + "・".join([f"{n} {await finish(n, n)}" for n in "ABCD"])]
    lines.append(f"2. D が Retry-After の 2 秒後に話し直す：{await finish('D', 'D2')}")
    await recognized(rec, v["A"], tasks.pop("A"), "A")
    lines.append("3. A の認識が終わり、返答の読み上げが始まる")
    v["A"].sent.append("interrupted")
    v["A"].turns.to(TurnState.LISTENING, "barge_in")
    lines.append(f"4. B・C の認識が終わる前に、A が割り込んで話し直す：{await finish('A', 'A2')}")
    for job, name in (("B", "B"), ("C", "C"), ("A2", "A")):
        await recognized(rec, v[name], tasks.pop(job), job)
    for name in "ABC":
        v[name].turns.to(TurnState.LISTENING, "playback_done")

    lines.append("STT の待ち＋処理（いちばん長い場合・1件 2.4 秒）："
                 + "・".join(f"{'A の2回目' if j == 'A2' else j} {s} 秒" for j, s in upper.items()))
    lines += [f"{name}: {path(v[name].turns)}" for name in "ABCD"]
    lines.append(f"D に送ったもの：{'・'.join(v['D'].sent)}")
    lines.append(f"入口の統計：認識した {rec.done} 件・断った {gate.rejected} 件・同時に動いた最大 {rec.max_active} 件")

    sentences = split_sentences(REPLY)
    slots = 1 + 3                                                # TTS の入口：同時 1・待ち 3（セッション14）
    lines.append(f"A の返答：{len(sentences)} 文（{'／'.join(sentences)}）")
    lines.append(f"TTS の入口（同時 1・待ち 3）：{len(sentences)} 文を一度に頼むと {min(len(sentences), slots)}/{slots} 枠を"
                 f"1人で使う・1文ずつ頼めば 1/{slots} 枠")
    return lines


def main() -> None:
    print("\n".join(asyncio.run(simulate())))


if __name__ == "__main__":
    main()
