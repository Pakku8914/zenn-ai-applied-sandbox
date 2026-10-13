"""問題2：再生の見積もりから interrupted の index を求め、実際の再生とずれる時間帯を調べる。

    docker compose exec api python -m src.session11.solutions.q2_playback_gap
"""

from __future__ import annotations

from src.session11.playback import PlaybackEstimate

SENT = [("1文目", 8.5, 0.0), ("2文目", 4.5, 2.0), ("3文目", 5.5, 4.0)]    # (文, 音声の秒数, 送り終えた時刻)


def build(lead_s: float) -> PlaybackEstimate:
    p = PlaybackEstimate(lead_s=lead_s)
    for text, seconds, sent_at in SENT:
        p.add(text, seconds, sent_at)
    return p


def mismatch_windows(est_lead: float, real_lead: float) -> list[tuple[float, float]]:
    """サーバーは「鳴り終えた」と見なすが、クライアントではまだ鳴っている時間帯。"""
    est, real = build(est_lead), build(real_lead)
    return [(e, r) for e, r in zip(est.ends, real.ends) if e < r]


def main() -> int:
    est = build(0.25)
    print(f"見積もり（lead 0.25 秒）の鳴り終わり: {est.ends}")
    print(" ／ ".join(f"{t} 秒 → index {est.heard_count(t)}" for t in (8.0, 10.0, 14.0)))
    print(f"実際は 1.0 秒遅れて鳴り始めたとき: {build(1.0).ends}")
    windows = "・".join(f"{a}〜{b} 秒" for a, b in mismatch_windows(0.25, 1.0))
    print(f"食い違う時間帯: {windows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
