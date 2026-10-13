"""問題1：起きた出来事の列から、ターンの状態の列を求める。

    docker compose exec api python -m src.session11.solutions.q1_turn_events
"""

from __future__ import annotations

from src.session11.turns import TurnMachine, TurnState

L, T, S = TurnState.LISTENING, TurnState.THINKING, TurnState.SPEAKING
# 出来事 → {いまの状態: 次の状態}。表に無い組み合わせは、その状態では起きないはずの出来事（コードの誤り）
RULES: dict[str, dict[TurnState, TurnState]] = {
    "speech_end": {L: T},
    "first_audio": {T: S},
    "no_reply": {T: L},
    "playback_done": {S: L},
    "barge_in": {T: L, S: L},
}
IGNORED = {"noise"}          # 割り込みに届かなかった音：どの状態でも何も変えない

CASES = {
    "A ふつうの1往復": ["speech_end", "first_audio", "playback_done"],
    "B 読み上げ中の割り込み": ["speech_end", "first_audio", "noise", "barge_in", "speech_end", "first_audio",
                         "playback_done"],
    "C 考えている間の割り込み": ["speech_end", "barge_in", "speech_end", "no_reply"],
    "D 誤り": ["speech_end", "playback_done"],
}


def replay(events: list[str]) -> list[str]:
    m = TurnMachine()
    for ev in events:
        if ev in IGNORED:
            continue
        nxt = RULES[ev].get(m.state)
        if nxt is None:
            raise ValueError(f"{m.state} で {ev} は起きません")
        m.to(nxt, ev)
    return [s for s, _ in m.log]


def main() -> int:
    for name, events in CASES.items():
        try:
            print(f"{name}: {' → '.join(replay(events))}")
        except ValueError as e:
            print(f"{name}: ValueError（{e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
