"""問題5：/ws/voice の下りメッセージの記録を、API契約⑤（セッション9・10）とターンの状態機械（セッション11）で検査する。

    docker compose exec api python -m src.review03.solutions.q5_ws_log
"""

from __future__ import annotations

from src.review03 import samples
from src.review03.kit import KEYS, VOICE_CREDIT, TurnMachine, TurnState
from src.review03.solutions.q3_heard import state_path

L, T, S = TurnState.LISTENING, TurnState.THINKING, TurnState.SPEAKING


def is_msg(m: object, kind: str) -> bool:
    return isinstance(m, dict) and m.get("type") == kind


def label(m: dict | bytes) -> str:
    if isinstance(m, bytes):
        return "wav"
    if m["type"] == "vad":
        return f"vad:{m['state']}"
    if m["type"] in ("audio", "interrupted"):
        return f"{m['type']}:{m['index']}"
    return m["type"]


def audit(log: list[dict | bytes]) -> tuple[TurnMachine, str]:
    """(状態機械, 結果)。結果は「違反なし」か「{n} 通目 {メッセージ}: {理由}」（最初に見つけた1件）。"""
    m = TurnMachine()

    def fail(i: int, why: str) -> tuple[TurnMachine, str]:
        return m, f"{i + 1} 通目 {label(log[i])}: {why}"

    if not log or not is_msg(log[0], "ready") or log[0].get("credit") != VOICE_CREDIT:
        return fail(0, f"1通目は credit「{VOICE_CREDIT}」付きの ready にする")
    open_turn, sent = False, 0                       # ターンが開いているか・そのターンで送った audio の数
    for i in range(1, len(log)):
        msg, prev = log[i], log[i - 1]
        if isinstance(msg, bytes):
            if not (is_msg(prev, "audio") and prev["bytes"] == len(msg)):
                return fail(i, "バイナリは audio の直後に、bytes と同じ長さで送る")
            continue
        kind = msg["type"]
        try:
            if kind == "vad" and msg["state"] == "speech_end":
                m.to(T, "speech_end")
                open_turn, sent = True, 0
            elif kind == "vad":                      # speech_start
                follows = is_msg(log[i + 1], "interrupted") if i + 1 < len(log) else False
                if not follows and m.state == S and not open_turn:
                    m.to(L, "playback_done")         # 返答を送り終え、鳴り終わったあとの話し始め
            elif kind == "audio":
                if msg["index"] != sent:
                    return fail(i, f"audio の index は {sent} のはず")
                if sent == 0:
                    m.to(S, "first_audio")
                sent += 1
            elif kind in ("turn_end", "error"):
                if not open_turn:
                    return fail(i, "開いていないターンを閉じている")
                if kind == "turn_end":
                    lat = msg["latency_ms"]
                    if list(lat) != list(KEYS) or (lat["first_audio"] is None) != (sent == 0):
                        return fail(i, "latency_ms の first_audio が null なのは audio を送らなかったターンだけ")
                if m.state == T:
                    m.to(L, "no_reply")
                open_turn = False
            elif kind == "interrupted":
                if not (is_msg(prev, "vad") and prev["state"] == "speech_start"):
                    return fail(i, "interrupted の直前には vad の speech_start を送る")
                if msg["index"] > sent:
                    return fail(i, f"index が送った audio の数（{sent}）を超えている")
                m.to(L, "barge_in")
                open_turn = False
        except ValueError as e:                      # 状態機械の表に無い移り方
            return fail(i, str(e))
    return m, "違反なし"


def main() -> None:
    for name, tokens in samples.WS_LOGS:
        machine, result = audit(samples.ws_log(tokens))
        print(f"{name}: {state_path(machine)} ／ {result}")


if __name__ == "__main__":
    main()
