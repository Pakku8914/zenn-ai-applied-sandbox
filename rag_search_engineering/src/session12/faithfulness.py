#!/usr/bin/env python3
"""忠実性・根拠一致・回答可能性を測る。

    python src/session12/faithfulness.py

3つの検査を別々の列として残すのがこのスクリプトの主張である。
1つの総合点に潰すと「どれを直せばよいか」が消える。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import Bench, collect_cases  # noqa: E402

from ragkit.llm import FixtureClient  # noqa: E402

THRESHOLDS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def abstention_matrix(bench: Bench, cases) -> dict[str, int]:
    """回答可能性の判定を混同行列にする。誤りの向きで打ち手が変わる。"""
    m = {"答えるべきで答えた": 0, "答えるべきなのに黙った": 0,
         "黙るべきで黙った": 0, "黙るべきなのに答えた": 0}
    for c in cases:
        should_answer = any(g >= 1 for g in bench.qrels.get(c.query_id, {}).values())
        if should_answer:
            m["答えるべきで答えた" if c.judgement.answerable else "答えるべきなのに黙った"] += 1
        else:
            m["黙るべきなのに答えた" if c.judgement.answerable else "黙るべきで黙った"] += 1
    return m


def report(bench: Bench, label: str, cases) -> None:
    n = len(cases)
    answered = [c for c in cases if c.judgement.answerable]
    valid = [c for c in answered if c.judgement.citations_valid]
    print(f"\n=== {label}（{n} 件）===")
    for key, value in abstention_matrix(bench, cases).items():
        print(f"  {key:<22} {value:>3} 件")
    print(f"  引用あり                {sum(1 for c in answered if c.judgement.has_citation):>3} "
          f"/ 回答した {len(answered)} 件")
    print(f"  引用がすべて実在        {len(valid):>3} 件")
    print(f"  根拠一致（引用先が適合）{sum(1 for c in valid if c.judgement.grounded):>3} 件")
    print(f"  忠実性の平均（引用が有効なケース）: {mean([c.judgement.faithfulness for c in valid]):.3f}")
    print(f"  忠実性の平均（引用が無効なケース）: "
          f"{mean([c.judgement.faithfulness for c in answered if not c.judgement.citations_valid]):.3f}")
    print("  しきい値ごとの不合格件数（回答した中で）:")
    for t in THRESHOLDS:
        ng = sum(1 for c in answered if c.judgement.faithfulness < t)
        print(f"    faithfulness < {t:.1f} : {ng:>3} 件")


def main() -> None:
    bench = Bench()
    good = collect_cases(bench, FixtureClient("answers_v1"))
    flawed = collect_cases(bench, FixtureClient("answers_flawed_v1"))
    report(bench, "正常系カセット answers_v1", good)
    report(bench, "異常系カセット answers_flawed_v1", flawed)
    print("\n引用が無効なケースの忠実性が 0.000 になるのは、照合先が1つも無いためである。")
    print("『引用が実在するか』を先に通さないと、忠実性の数字は意味を持たない。")


if __name__ == "__main__":
    main()
