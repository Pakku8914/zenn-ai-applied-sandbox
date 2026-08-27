#!/usr/bin/env python3
"""セッション5の自己検証（その3）：全部を大きいモデルに送らないこと。

- 既定は「測って速かった階層」に送る
- 長い出力が必要なものだけ品質階層へ上げる
- 上流が不調なら速い階層へ落として出力も切り詰める（縮退を記録する）
- どの階層にも収まらない長さは受ける前に断る（413）

**推論サーバは不要**（振り分けは純粋な関数）。

  docker compose exec app python src/session05/verify_routing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from routing import FAST, QUALITY, TIERS, route, routing_table  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print("=== 階層の実測値（2026-08-15・スロット1・ctx1024・max_tokens=48・並列1）===")
for tier in TIERS:
    print(f"{tier.name:<8}: {tier.model_file:<20} "
          f"TTFT p50 {tier.measured_ttft_p50_ms:.0f} ms / {tier.measured_tps:.1f} tok/s")

check("速い階層は実測で速い（小さいほど速いとは限らない）",
      FAST.measured_ttft_p50_ms < QUALITY.measured_ttft_p50_ms
      and FAST.measured_tps > QUALITY.measured_tps,
      f"Q8_0 {FAST.measured_ttft_p50_ms:.0f}ms vs f16 "
      f"{QUALITY.measured_ttft_p50_ms:.0f}ms")

print("\n=== 振り分け ===")
print(routing_table())

default = route(200, 64)
check("短い対話は既定で速い階層へ",
      default.tier == "fast" and not default.degraded, default.reason)

long_out = route(200, 200)
check("長い出力が要るときだけ品質階層へ",
      long_out.tier == "quality" and long_out.max_tokens == 200, long_out.reason)

batch = route(200, 200, priority="batch")
check("急がない要求は速い階層へ落とし、出力も切り詰める",
      batch.tier == "fast" and batch.max_tokens == 64 and batch.degraded,
      f"max_tokens {batch.max_tokens}（要求は 200）")

degraded = route(200, 64, upstream_degraded=True)
check("上流が不調なら縮退させ、そのことを記録する",
      degraded.tier == "fast" and degraded.degraded, degraded.reason)

too_long = route(1200, 64)
check("どの階層にも収まらない入力は受ける前に断る",
      too_long.status_code == 413 and too_long.max_tokens == 0, too_long.reason)

invalid = route(0, 64)
check("入力が空なら 400 で断る", invalid.status_code == 400, invalid.reason)

check("出力上限は必ず階層の上限以下に抑えられる",
      route(200, 9999).max_tokens == QUALITY.max_output_tokens,
      f"要求 9999 -> {route(200, 9999).max_tokens}（品質階層の上限）")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5（モデル階層への振り分け）の検証はすべて成功しました。")
