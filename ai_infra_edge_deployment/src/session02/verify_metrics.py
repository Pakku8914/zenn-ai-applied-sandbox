#!/usr/bin/env python3
"""セッション2の追加検証：指標の計算そのものが正しいこと。

推論サーバもモデルも使わないので、いつでも実行できる。

    docker compose exec app python src/session02/verify_metrics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))                              # infrakit を読むため
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 同じ階層の metrics.py を読むため

from infrakit.load import percentiles  # noqa: E402
from metrics import (  # noqa: E402
    check_slo,
    comparable,
    effective_quantile,
    min_samples,
    rebuild_total,
    requests_per_second,
    split_tpot,
    spread,
    tokens_per_second,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print("=== 指標の分解 ===")
tpot = split_tpot(total_ms=1000.0, ttft_ms=100.0, tokens_out=46)
check("TPOT は TTFT を引いてから割る", tpot == 20.0, f"{tpot:.1f}ms/token")
check("TTFT と TPOT から総時間を組み立て直せる",
      rebuild_total(100.0, tpot, 46) == 1000.0, f"{rebuild_total(100.0, tpot, 46):.0f}ms")
check("出力を2倍にした見積もりが作れる",
      rebuild_total(100.0, tpot, 91) == 1900.0, f"{rebuild_total(100.0, tpot, 91):.0f}ms")
check("1トークンだけなら TPOT は定義できない", split_tpot(500.0, 500.0, 1) == 0.0)

print("\n=== スループットの2つの単位 ===")
tps = tokens_per_second(960, 20_000.0)
rps = requests_per_second(20, 20_000.0)
check("トークン/秒", tps == 48.0, f"{tps:.1f} tok/s")
check("リクエスト/秒", rps == 1.0, f"{rps:.2f} rps")
check("1件48トークンなら tok/s = 48 × rps", tps == 48.0 * rps)

print("\n=== p50 と p95 に必要な件数 ===")
many = percentiles([float(v) for v in range(10, 210, 10)])   # 20件
few = percentiles([10.0, 20.0, 30.0, 40.0, 50.0])            # 5件
check("20件の p50 は中央2件の平均", many["p50"] == 105.0, str(many["p50"]))
check("20件の p95 は上から2番目", many["p95"] == 190.0, str(many["p95"]))
check("5件の p95 も上から2番目にすぎない", few["p95"] == 40.0, str(few["p95"]))
check("5件で p95 と名乗った値は実際には p80",
      effective_quantile(5) == 0.8,
      f"5件 -> p{effective_quantile(5) * 100:.0f} / 20件 -> p{effective_quantile(20) * 100:.0f}")
check("p90 を語るには10件必要", min_samples(0.90) == 10, f"{min_samples(0.90)} 件")
check("p95 を語るには20件必要", min_samples(0.95) == 20, f"{min_samples(0.95)} 件")
check("p99 を語るには100件必要", min_samples(0.99) == 100, f"{min_samples(0.99)} 件")
check("空のリストでも落ちない", percentiles([])["p50"] == 0.0)

print("\n=== ばらつきと条件の一致 ===")
check("p95 ÷ p50 でばらつきを見る", spread({"p50": 100.0, "p95": 300.0}) == 3.0)
base = {"max_tokens": 48, "warmup": 2, "model": "qwen05b-q4_k_m.gguf", "n_ctx": 1024, "slots": 2}
same = dict(base)
other = dict(base, max_tokens=24)
check("同じ条件なら並べて比較してよい", comparable(base, same) == [])
check("max_tokens が違うレポートは並べられない",
      comparable(base, other) == ["max_tokens"], str(comparable(base, other)))

print("\n=== SLO の判定 ===")
observed = {"ttft": {"p50": 1772.0, "p95": 2064.0}, "total": {"p50": 3379.0, "p95": 3737.0}}
violations = check_slo(observed, {"ttft.p95": 500.0, "total.p95": 5000.0})
check("TTFT の p95 が SLO を超えたことを検出する", violations == ["ttft.p95"], str(violations))
check("満たしている項目は挙がらない", check_slo(observed, {"total.p95": 5000.0}) == [])

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション2（指標の計算）の検証はすべて成功しました。")
