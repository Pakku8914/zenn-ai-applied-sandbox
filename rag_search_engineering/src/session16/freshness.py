#!/usr/bin/env python3
"""鮮度：文書の古さと、索引の遅れを分けて測る。

  ① 文書の古さ  = as-of（いつ時点の話か）− 元データの更新日
  ② 索引の遅れ  = 索引に載った日 − 元データの更新日   ← 鮮度 SLO はこちら

②は「いつバッチを回したか」で決まる。ここでは 2026-05-15 と 2026-08-16 の
2回だけ回した運用を再現し、日次で回した場合と比べる。

    python src/session16/freshness.py
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ASOF, lag_days, percentile  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.corpus import load_docs  # noqa: E402

RUN1 = "2026-05-15"  # 初回構築（バックフィル）
RUN2 = "2026-08-16"  # 2回目のバッチ
SLO_DAYS = 7  # 「更新から7日以内に検索できる」を SLO にする


def indexed_at_batch(updated_at: str) -> str:
    """2回だけ回したバッチのうち、その文書が索引に載った日。"""
    return RUN1 if updated_at <= RUN1 else RUN2


def indexed_at_daily(updated_at: str) -> str:
    """日次バッチなら、翌日には載る。"""
    return (date.fromisoformat(updated_at) + timedelta(days=1)).isoformat()


def slo_rate(lags: list[int], slo_days: int = SLO_DAYS) -> float:
    if not lags:
        return 0.0
    return round(100.0 * sum(1 for x in lags if x <= slo_days) / len(lags), 1)


def main() -> None:
    docs = load_docs()

    print(f"=== 1. 文書の古さ（as-of {ASOF}）===")
    ages = [lag_days(d.updated_at, ASOF) for d in docs]
    dist = Counter((d.updated_at, lag_days(d.updated_at, ASOF)) for d in docs)
    print("  更新日        件数   古さ(日)")
    for (updated, age), n in sorted(dist.items()):
        print(f"  {updated}   {n:>4}   {age:>6}")
    print(f"  中央値 {percentile(ages, 0.5)} 日 / p95 {percentile(ages, 0.95)} 日 / "
          f"最大 {max(ages)} 日")
    print(f"  当日更新（古さ0日）: {sum(1 for a in ages if a == 0)} 件 / "
          f"1年以上前: {sum(1 for a in ages if a >= 365)} 件")

    print(f"\n=== 2. 索引の遅れ（バッチを {RUN1} と {RUN2} の2回だけ回した場合）===")
    backfill = [d for d in docs if d.updated_at <= RUN1]
    target = [d for d in docs if d.updated_at > RUN1]
    print(f"  初回構築で載った文書（SLO の対象外）: {len(backfill)} 件")
    print(f"  SLO の対象（初回構築より後の更新）  : {len(target)} 件")
    lags = [lag_days(d.updated_at, indexed_at_batch(d.updated_at)) for d in target]
    for lag, n in sorted(Counter(lags).items()):
        print(f"    遅れ {lag:>3} 日: {n} 件")
    print(f"  遅れ 中央値 {percentile(lags, 0.5)} 日 / p95 {percentile(lags, 0.95)} 日 / "
          f"最大 {max(lags)} 日")
    print(f"  SLO（{SLO_DAYS}日以内）達成率: {slo_rate(lags)} %")

    print("\n=== 3. 日次バッチに変えたら ===")
    daily = [lag_days(d.updated_at, indexed_at_daily(d.updated_at)) for d in target]
    print(f"  遅れ 最大 {max(daily)} 日 / SLO 達成率: {slo_rate(daily)} %")
    print("  遅れを縮めるのはモデルでもチャンク方式でもなく、バッチの間隔。")


if __name__ == "__main__":
    main()
