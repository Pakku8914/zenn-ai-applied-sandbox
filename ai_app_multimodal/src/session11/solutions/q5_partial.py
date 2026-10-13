"""問題5：途中まで聞いた文も、時間の割合で文字を切って履歴に残す。

    docker compose exec api python -m src.session11.solutions.q5_partial
"""

from __future__ import annotations

from src.session11.history import Conversation
from src.session11.playback import PlaybackEstimate

S0 = "鶏むね肉とキャベツがあるなら、20分以内で作れる「鶏むね肉とキャベツの塩炒め」がおすすめです。"
S1 = "鶏むね肉をそぎ切りにして、片栗粉を薄くまぶします。"


def heard_with_partial(p: PlaybackEstimate, now: float) -> list[str]:
    """鳴り終えた文と、鳴っている途中の文の「鳴った割合ぶんの文字」＋「…」。"""
    n = p.heard_count(now)
    heard = p.texts[:n]
    if n < len(p.texts) and p.starts[n] < now:
        ratio = (now - p.starts[n]) / (p.ends[n] - p.starts[n])
        chars = int(len(p.texts[n]) * ratio)          # 切り捨て：言い切っていない文字は残さない
        if chars:
            heard.append(p.texts[n][:chars] + "…")
    return heard


def demo() -> PlaybackEstimate:
    p = PlaybackEstimate(lead_s=0.0)
    p.add(S0, 8.0, 0.0)          # 0〜8 秒に鳴る
    p.add(S1, 4.0, 1.0)          # 8〜12 秒に鳴る
    return p


def main() -> int:
    p = demo()
    for now in (6.0, 10.0):
        c = Conversation()
        c.add_assistant(heard_with_partial(p, now), interrupted=True)
        print(f"{now} 秒で割り込み:\n{c.messages[0]['content']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
