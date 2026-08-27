#!/usr/bin/env python3
"""静的バッチと連続バッチの完了時刻を比べる（セッション3・問題7の解答）。

1ステップの時間は同時実行数によらず一定と仮定した最小のシミュレーション。
実際の推論サーバでは同時実行数が増えると1ステップの時間も伸びるので、ここで出る
比は「待ち行列だけを取り除いたときの上限」として読む。プリフィルは無視している。

  python src/session03/batching_sim.py                        # 既定（12 2 6 10 / 2席）
  python src/session03/batching_sim.py --steps 16 4 8 4        # 本文の例
  python src/session03/batching_sim.py --slots 3               # 席を増やす
"""

from __future__ import annotations

import argparse
import heapq
import string


def static_batch(jobs: list[tuple[str, int]], slots: int) -> dict[str, int]:
    """到着順に slots 件ずつまとめ、そのバッチが全部終わるまで席を空けない。

    先に生成が終わった要求も、バッチの最長が終わるまで待たされる。
    """
    done: dict[str, int] = {}
    t = 0
    for i in range(0, len(jobs), slots):
        group = jobs[i:i + slots]
        t += max(steps for _, steps in group)
        for name, _ in group:
            done[name] = t
    return done


def continuous_batch(jobs: list[tuple[str, int]], slots: int) -> dict[str, int]:
    """空くのが最も早い席に、到着順で次の要求を座らせる（連続バッチ）。"""
    free = [0] * slots
    heapq.heapify(free)
    done: dict[str, int] = {}
    for name, steps in jobs:
        start = heapq.heappop(free)
        finish = start + steps
        done[name] = finish
        heapq.heappush(free, finish)
    return done


def average(values) -> float:
    values = list(values)
    return sum(values) / len(values)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, nargs="+", default=[12, 2, 6, 10],
                    help="各要求のデコードのステップ数（到着順）")
    ap.add_argument("--slots", type=int, default=2)
    args = ap.parse_args()

    jobs = [(string.ascii_uppercase[i], s) for i, s in enumerate(args.steps)]
    st = static_batch(jobs, args.slots)
    co = continuous_batch(jobs, args.slots)

    print(f"=== {len(jobs)} 件の要求（デコードのステップ数）===")
    print(" / ".join(f"{n}: {s}" for n, s in jobs) + f"   スロット数={args.slots}")

    print("\n要求ごとの完了時刻（ステップ）")
    for name, _ in jobs:
        print(f"{name}: 静的={st[name]:>3} / 連続={co[name]:>3}")

    a, b = average(st.values()), average(co.values())
    print(f"\n平均完了時間: 静的={a:.1f} → 連続={b:.1f} ステップ（{b / a:.2f} 倍）")
    print(f"最後の完了  : 静的={max(st.values())} → 連続={max(co.values())} ステップ")
    print("\n※ 必要ステップの合計は両者で同じ。変わったのは「いつ席に座れたか」だけ。")


if __name__ == "__main__":
    main()
