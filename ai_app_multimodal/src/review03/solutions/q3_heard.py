"""問題3：Markdown の返答を文に分けて（セッション9）、差分から文を組み立てて送り（セッション10）、
話しかけた時刻ごとに「どこまで伝わったか」と会話履歴を求める（セッション11）。時計も音も使わない計算だけ。

    docker compose exec api python -m src.review03.solutions.q3_heard
"""

from __future__ import annotations

from src.review03 import samples
from src.review03.kit import (
    INTERRUPTED_NOTE, LOOPBACK_TEXT, PLAYBACK_LEAD_S, Conversation, PlaybackEstimate, SentenceBuffer, TurnMachine,
    TurnState, split_sentences,
)

DELTA_CHARS = 6        # LLM の差分は 6 文字ずつ届く
DELTA_STEP = 10        # k 個目の差分は k/10 秒に届く（0.1 秒ごと）
CHAR_SECONDS = 0.125   # 読み上げは 1 文字 0.125 秒（合成は一瞬で終わるとする）
TIMES = (0.5, 5.0, 8.0, 12.0, None)   # 話しかけた時刻（None は最後まで話しかけない。30.0 秒の時点で見る）
QUIET_UNTIL = 30.0


def ready_at(reply: str) -> tuple[list[tuple[str, int | None]], int]:
    """(文, その文が完成した差分の番号。flush で出たものは None) の列と、差分の総数。"""
    buf, out, n = SentenceBuffer(), [], 0
    for n, i in enumerate(range(0, len(reply), DELTA_CHARS), 1):
        out += [(s, n) for s in buf.feed(reply[i:i + DELTA_CHARS])]
    out += [(s, None) for s in buf.flush()]
    return out, n


def sent_times(ready: list[tuple[str, int | None]], total: int) -> list[float]:
    return [(k if k is not None else total) / DELTA_STEP for _, k in ready]


def replay(ready: list[tuple[str, int | None]], total: int, at: float | None) -> tuple[TurnMachine, Conversation, int | None]:
    """at 秒に話しかけたら（None なら最後まで聞いたら）、状態・履歴・interrupted の index がどうなるか。"""
    now = QUIET_UNTIL if at is None else at
    machine, history, playback = TurnMachine(), Conversation(), PlaybackEstimate(PLAYBACK_LEAD_S)
    history.add_user(LOOPBACK_TEXT)
    machine.to(TurnState.THINKING, "speech_end")
    for (text, _), sent_at in zip(ready, sent_times(ready, total), strict=True):
        if sent_at > now:
            break
        playback.add(text, len(text) * CHAR_SECONDS, sent_at)
        if machine.state == TurnState.THINKING:
            machine.to(TurnState.SPEAKING, "first_audio")
    if machine.state == TurnState.THINKING:              # まだ何も鳴らしていない：assistant は残さない
        machine.to(TurnState.LISTENING, "barge_in")
        return machine, history, 0
    if at is None:                                       # 話しかけずに、見積もりの鳴り終わりを過ぎた
        history.add_assistant(playback.heard(now), interrupted=False)
        machine.to(TurnState.LISTENING, "playback_done")
        return machine, history, None
    index = playback.heard_count(now)
    history.add_assistant(playback.heard(now), interrupted=True)
    machine.to(TurnState.LISTENING, "barge_in")
    return machine, history, index


def state_path(machine: TurnMachine) -> str:
    """listening に戻ったところだけ理由を添える（barge_in・no_reply・playback_done）。"""
    return " → ".join(f"{s}（{why}）" if i and s == "listening" else s for i, (s, why) in enumerate(machine.log))


def describe(message: dict) -> str:
    lines = message["content"].split("\n")
    if message["role"] == "user":
        return f"user {len(lines)}行"
    noted = lines[-1] == INTERRUPTED_NOTE
    n = len(lines) - noted
    if noted:
        return "assistant 割り込みの印だけ" if n == 0 else f"assistant {n} 文＋割り込みの印"
    return f"assistant {n} 文"


def history_text(messages: list[dict]) -> str:
    return " ／ ".join(describe(m) for m in messages)


def sec(x: float) -> str:
    return str(round(x, 3))


def main() -> None:
    reply = samples.kondate_reply()
    ready, total = ready_at(reply)
    assert [s for s, _ in ready] == split_sentences(reply)   # 流しても、全文を分けたときと同じ文になる
    print(f"文の数: {len(ready)}（番号付きリストの「1.」「2.」「3.」と空行は読まない）")
    print(f"文ができた差分: {'・'.join(str(k) if k else 'flush' for _, k in ready)}（差分は全 {total} 個）")
    print(f"送り終えた時刻: {'・'.join(sec(t) for t in sent_times(ready, total))} 秒")
    estimate = PlaybackEstimate(PLAYBACK_LEAD_S)
    for (text, _), t in zip(ready, sent_times(ready, total), strict=True):
        estimate.add(text, len(text) * CHAR_SECONDS, t)
    print(f"鳴り終わりの見積もり: {'・'.join(sec(e) for e in estimate.ends)} 秒")
    for at in TIMES:
        machine, history, index = replay(ready, total, at)
        head = f"{QUIET_UNTIL} 秒まで話しかけない" if at is None else f"{at} 秒に話しかける"
        idx = "なし" if index is None else str(index)
        print(f"{head} → {state_path(machine)}・interrupted {idx}・履歴 {history_text(history.messages)}")


if __name__ == "__main__":
    main()
