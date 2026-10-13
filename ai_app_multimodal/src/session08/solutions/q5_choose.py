"""問題5：測った表から、条件を満たすいちばん軽い設定を選ぶ。処理できる量も見積もる。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Measured:
    model: str
    beam: int
    cer: float
    rtf: float
    rss_mib: int


# 10文・合計 32.1 秒・辞書なし・int8・2 スレッド（2026-10-02・Apple Silicon＋Rancher Desktop の VM 2 CPU）
MEASURED = [
    Measured("tiny", 5, 0.309, 0.135, 249),
    Measured("base", 5, 0.321, 0.208, 339),
    Measured("small", 5, 0.115, 0.638, 627),
    Measured("small", 1, 0.115, 0.578, 627),
]


def choose(rows: list[Measured], *, max_cer: float, max_rtf: float, max_rss_mib: int) -> Measured | None:
    """条件をすべて満たす候補のうち、RTF（同じなら メモリ）がいちばん小さいもの。無ければ None。"""
    ok = [r for r in rows if r.cer <= max_cer and r.rtf <= max_rtf and r.rss_mib <= max_rss_mib]
    return min(ok, key=lambda r: (r.rtf, r.rss_mib), default=None)


def utterances_per_minute(rtf: float, utterance_seconds: float) -> float:
    """limiter が同時1件のとき、1分間に認識し終えられる発話の数（待ち時間は考えない上限）。"""
    return 60 / (rtf * utterance_seconds)


if __name__ == "__main__":
    best = choose(MEASURED, max_cer=0.15, max_rtf=0.8, max_rss_mib=1024)
    print(f"選んだ設定：{best}")
    print(f"4 秒の発話なら 1 分に {utterances_per_minute(best.rtf, 4.0):.1f} 件まで")
