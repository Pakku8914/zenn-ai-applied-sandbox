#!/usr/bin/env python3
"""セッション2の自己検証：推論サーバを測れていること。

推論サーバが起動していない場合は SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if os.environ.get("SKIP_SERVER") == "1":
    print("SKIP_SERVER=1 のため推論サーバの検証を飛ばします。")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.client import LlamaClient  # noqa: E402
from infrakit.load import percentiles, run_load  # noqa: E402
from tools.prompts import with_shared_prefix  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


client = LlamaClient()
check("推論サーバに接続できる", client.health(),
      "つながらない場合は `docker compose up -d llama` を実行してください")
if failures:
    sys.exit(1)

props = client.props()
slots = client.slots()
check("スロットの状態が取れる", len(slots) > 0, f"{len(slots)} スロット")
check("モデルが読み込まれている", bool(props.get("model_path")),
      str(props.get("model_path", ""))[-40:])

# --- 1リクエストの計測 ------------------------------------------------------
prompts = with_shared_prefix()
r = client.generate(prompts[0], max_tokens=32)
check("生成が成功する", r.ok, r.error or f"{r.tokens_out} トークン")
check("TTFT が総時間より小さい", r.ttft_ms < r.total_ms,
      f"TTFT {r.ttft_ms:.0f}ms < 総時間 {r.total_ms:.0f}ms")
check("TPOT が妥当な範囲", 0 < r.tpot_ms < 5000, f"{r.tpot_ms:.1f}ms/token")
check("トークンが生成されている", r.tokens_out > 5, f"{r.tokens_out} トークン")
check("日本語が返ってくる", any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿"
                              for ch in r.text), repr(r.text[:40]))

# --- パーセンタイルの計算 ---------------------------------------------------
p = percentiles([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
check("p50 が中央値になる", p["p50"] == 55.0, str(p["p50"]))
check("max が最大値になる", p["max"] == 100.0, str(p["max"]))
check("空のリストでも落ちない", percentiles([])["p50"] == 0.0)

# --- ウォームアップの有無で数字が変わる（S02 の主題）------------------------
cold = run_load(client, prompts[:5], concurrency=1, max_tokens=16, warmup=0, label="cold")
warm = run_load(client, prompts[:5], concurrency=1, max_tokens=16, warmup=2, label="warm")
print(f"\nウォームアップ無し: {cold.summary()}")
print(f"ウォームアップ有り: {warm.summary()}")
check("どちらもエラーなく完走する", cold.errors == 0 and warm.errors == 0)
check("測定条件がレポートに残る", cold.conditions.get("warmup") == 0
      and warm.conditions.get("warmup") == 2, str(warm.conditions))

# --- 同時実行数を上げると TTFT が悪化する（飽和）----------------------------
n_slots = len(slots)
c_low = run_load(client, prompts[:8], concurrency=1, max_tokens=24, label="c1")
c_over = run_load(client, prompts[:8], concurrency=n_slots * 2, max_tokens=24,
                  label=f"c{n_slots * 2}")
print(f"\n並列 1        : {c_low.summary()}")
print(f"並列 {n_slots * 2}（スロット数の2倍）: {c_over.summary()}")
check("スロット数を超えると TTFT が悪化する",
      c_over.ttft["p50"] > c_low.ttft["p50"],
      f"{c_low.ttft['p50']:.0f}ms -> {c_over.ttft['p50']:.0f}ms")
check("スループットは同時実行を増やしても比例しない",
      c_over.throughput_tps < c_low.throughput_tps * n_slots * 2,
      f"{c_low.throughput_tps:.1f} -> {c_over.throughput_tps:.1f} tok/s")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション2の検証はすべて成功しました。")
