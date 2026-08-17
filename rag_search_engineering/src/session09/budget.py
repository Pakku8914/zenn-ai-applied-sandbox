#!/usr/bin/env python3
"""レイテンシ予算から「リランクに渡してよい候補数の上限」を逆算する。

数値は tools/bench_rerank.py の実測（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13）をそのまま定数に写している。モデルを使わないので数秒で終わる。

実行:  docker compose exec app python src/session09/budget.py
"""

from __future__ import annotations

# 候補数 -> (中央値 ms, 最大 ms, 1件あたり ms)
MEASURED: dict[int, tuple[float, float, float]] = {
    10: (405.0, 416.0, 40.5),
    20: (709.0, 724.0, 35.4),
    50: (1571.0, 1585.0, 31.4),
    100: (2710.0, 2866.0, 27.1),
}

BUDGET_MS = 500.0  # このサービスが検索に使ってよい時間
STAGE1_MS = 20.0  # 1段目（クエリの符号化 9.8ms + ANN 探索 + 前後処理）に引き当てる分


def fit_two_point(lo: int = 10, hi: int = 20) -> tuple[float, float]:
    """予算の近くにある2点だけで直線を引く（局所モデル）。

    リランクの所要時間は候補数に対して厳密には直線ではない（1件あたりの
    コストが下がっていく）ので、答えを出したい範囲の近くで当てるほうが精度が高い。
    """
    t_lo, t_hi = MEASURED[lo][0], MEASURED[hi][0]
    slope = (t_hi - t_lo) / (hi - lo)
    return slope, t_lo - slope * lo


def fit_least_squares() -> tuple[float, float]:
    """4点すべてに最小二乗で直線を当てる（大域モデル）。"""
    ns = list(MEASURED)
    ts = [MEASURED[n][0] for n in ns]
    mean_n = sum(ns) / len(ns)
    mean_t = sum(ts) / len(ts)
    sxx = sum((n - mean_n) ** 2 for n in ns)
    sxy = sum((n - mean_n) * (t - mean_t) for n, t in zip(ns, ts))
    slope = sxy / sxx
    return slope, mean_t - slope * mean_n


def max_candidates(model: tuple[float, float], budget_ms: float) -> float:
    """予算 budget_ms に収まる候補数（小数のまま返す。切り捨ては呼び出し側）。"""
    slope, intercept = model
    return (budget_ms - intercept) / slope


MODELS = {"局所2点モデル  ": fit_two_point(), "最小二乗モデル ": fit_least_squares()}


def main() -> None:
    print("=== リランクのレイテンシ実測（tools/bench_rerank.py / 2026-08-15 / "
          "aarch64 / CPU 2コア）===")
    for n, (med, mx, per) in MEASURED.items():
        print(f"  候補 {n:>3} 件 : 中央値 {med:>5.0f} ms / 最大 {mx:>5.0f} ms / "
              f"1件あたり {per:>4.1f} ms")

    two, ls = fit_two_point(), fit_least_squares()
    print("\n=== 直線モデル（t = 傾き × 候補数 + 切片）===")
    print(f"  局所2点（候補10と20） : t(n) = {two[0]:.1f} * n + {two[1]:.0f} ms")
    print(f"  全4点の最小二乗       : t(n) = {ls[0]:.1f} * n + {ls[1]:.0f} ms")

    print("\n=== レイテンシ予算からの逆算 ===")
    answers: list[int] = []
    cases = [
        (f"予算 {BUDGET_MS:.0f} ms のうち 1段目に {STAGE1_MS:.0f} ms を引き当てる",
         BUDGET_MS - STAGE1_MS),
        (f"予算 {BUDGET_MS:.0f} ms をすべてリランクに使う", BUDGET_MS),
    ]
    for label, rerank_ms in cases:
        print(f"  {label} -> リランクに使えるのは {rerank_ms:.0f} ms")
        for name, model in MODELS.items():
            n = max_candidates(model, rerank_ms)
            answers.append(int(n))
            print(f"    {name}: n <= {n:.1f} -> {int(n)} 件")

    primary = int(max_candidates(two, BUDGET_MS - STAGE1_MS))
    print(f"\n結論: 上限候補数は {primary} 前後（モデルの取り方で "
          f"{min(answers)}〜{max(answers)} に振れる）")
    print("      境目の1件を議論しても意味はない。桁（10件台か100件台か）で決める。")


if __name__ == "__main__":
    main()
