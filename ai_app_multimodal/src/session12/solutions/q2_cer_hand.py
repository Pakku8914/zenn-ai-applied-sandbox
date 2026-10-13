"""問題2：4文の CER を、文字数加重と単純平均・厳密とゆれ吸収で集計する。

    docker compose exec api python -m src.session12.solutions.q2_cer_hand
"""

from __future__ import annotations

from kondate.metrics import normalize_ja
from src.session12.eval_cer import aggregate, edit_counts
from src.session12.textnorm import normalize_relaxed

PAIRS = [
    ("タイマーを5分にセットして。", "タイマーを5分にセットして"),
    ("今日は30分以内で作れる和食がいいな。", "今日は30分以内で作れるは食がいいな"),
    ("買い物リストに豆腐とわかめを追加して。", "買い物リストに豆腐と若目を追加して"),
    ("豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。", "豚コマ切れ肉と玉ネギの生姜焼きを4人分作りたい"),
]


def main() -> int:
    for (ref, _), (e, n), (er, _) in zip(PAIRS, edit_counts(PAIRS, normalize_ja), edit_counts(PAIRS, normalize_relaxed),
                                        strict=True):
        print(f"{ref}：厳密 {e}/{n}・ゆれ吸収 {er}/{n}")
    print(aggregate(PAIRS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
