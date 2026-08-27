#!/usr/bin/env python3
"""セッション13の自己検証：ランタイムのつまみは「関係」だけを検証する。

  python src/session13/verify_runtime.py

**レイテンシの絶対値は一切アサーションしない。** 同じ環境でも実行ごとに揺れるため、
絶対値を期待値に書いたテストは必ず壊れる。ここで検証するのは向きと関係だけ。

  ・規模が大きいほど遅い
  ・つまみを変えても**答えは変わらない**（速度とメモリだけが変わる）
  ・セッションは使い回すほうが1件あたり速い
  ・スレッド数を変えると値が変わる（最適点は環境依存なので断定しない）
  ・実在しない実行プロバイダは事前に落ち、CPU で動く
  ・バッチ次元を動的にしても、バッチ1の答えは固定形状のときと同じ
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    Knobs, available_providers, build_session, cpu_count, ensure_dynamic_batch,
    ensure_model, env_line, fixed_input, measure, model_pair, run_once,
    select_providers, size_mb,
)

REPEATS = 30
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print(f"測定条件: {env_line(REPEATS)}")
fp32, int8 = model_pair()
feeds = fixed_input()

# --- サイズ（決定的な関係）--------------------------------------------------
check("int8 のファイルは fp32 より小さい", size_mb(int8) < size_mb(fp32),
      f"{size_mb(fp32):.2f} MB -> {size_mb(int8):.2f} MB")

# --- ① 規模が大きいほど遅い -------------------------------------------------
small = ensure_model(1024)
p50_small = measure(build_session(small, Knobs(intra=1)), feeds, repeats=REPEATS)["p50"]
p50_large = measure(build_session(fp32, Knobs(intra=1)), feeds, repeats=REPEATS)["p50"]
check("規模が大きいほど遅い（隠れ層 1024 < 隠れ層 4096）", p50_small < p50_large,
      f"{size_mb(small):.2f} MB {p50_small:.2f}ms < "
      f"{size_mb(fp32):.2f} MB {p50_large:.2f}ms")

# --- ② つまみを変えても答えは変わらない -------------------------------------
base_out = run_once(build_session(int8, Knobs(intra=1)), feeds)
# 許容差は「メモリと並列度のつまみ」と「最適化レベル」で分ける。前者は計算そのものが
# 同じなのでほぼ完全一致し、後者は演算子の融合でカーネルが変わるため厳密一致しない。
variants = [
    ("アリーナ無効", Knobs(intra=1, arena=False), 1e-6),
    ("メモリパターン無効", Knobs(intra=1, mem_pattern=False), 1e-6),
    ("スレッド4", Knobs(intra=4), 1e-6),
    ("並列実行モード", Knobs(intra=1, inter=2, parallel=True), 1e-6),
    ("最適化なし", Knobs(intra=1, opt="disable"), 1e-4),
    ("基本最適化のみ", Knobs(intra=1, opt="basic"), 1e-4),
]
for name, knobs, atol in variants:
    got = run_once(build_session(int8, knobs), feeds)
    diff = float(np.abs(base_out - got).max())
    check(f"つまみを変えても答えは変わらない（{name}）",
          bool(np.allclose(base_out, got, atol=atol, rtol=0)),
          f"最大差 {diff:.2e}（許容 {atol:.0e}）")

# --- ③ セッションは使い回すほうが速い ---------------------------------------
knobs = Knobs(intra=1)
steady = measure(build_session(int8, knobs), feeds, repeats=REPEATS)["p50"]
each = []
for _ in range(5):
    t0 = time.perf_counter()
    build_session(int8, knobs).run(None, feeds)
    each.append((time.perf_counter() - t0) * 1000)
each.sort()
per_call = each[len(each) // 2]
check("セッションを毎回作ると1件あたりが遅くなる", per_call > steady,
      f"毎回作る {per_call:.2f}ms > 使い回す {steady:.2f}ms "
      f"（{per_call / max(steady, 1e-9):.1f} 倍）")

# --- ④ スレッド数を変えると値が変わる（最適点は断定しない）------------------
sweep = {intra: measure(build_session(int8, Knobs(intra=intra)), feeds,
                        repeats=REPEATS)["p50"] for intra in (1, 2, 4)}
print("   int8 の p50: " + " / ".join(f"intra={k} {v:.2f}ms" for k, v in sweep.items()))
best = min(sweep, key=lambda k: sweep[k])
print(f"   この環境（CPU {cpu_count()}コア）での最速は intra={best}。"
      "環境依存なので断定しません。")
check("スレッド数を変えるとレイテンシが変わる",
      len({round(v, 4) for v in sweep.values()}) > 1,
      "同じ値が並ぶなら、測定回数を増やすか規模を上げる")

# --- ⑤ 実行プロバイダの選択 -------------------------------------------------
picked = select_providers(["NoSuchExecutionProvider", "CUDAExecutionProvider"])
check("実在しない実行プロバイダは落とされ、CPU が残る",
      picked[-1] == "CPUExecutionProvider"
      and all(p in available_providers() for p in picked),
      f"要求 2 件 -> 採用 {picked}")
session = build_session(int8, Knobs(intra=1, providers=("NoSuchExecutionProvider",)))
check("落とした結果のリストでセッションが作れる",
      "CPUExecutionProvider" in session.get_providers(),
      f"実際に使った EP {session.get_providers()}")

# --- ⑥ バッチ次元を動的にしても答えは同じ -----------------------------------
dyn = ensure_dynamic_batch(fp32)
dyn_session = build_session(dyn, Knobs(intra=1))
fixed_out = run_once(build_session(fp32, Knobs(intra=1)), fixed_input(1))
dyn_out = run_once(dyn_session, fixed_input(1))
check("バッチ次元を動的にしてもバッチ1の答えは同じ",
      bool(np.allclose(fixed_out, dyn_out, atol=1e-5, rtol=0)),
      f"最大差 {float(np.abs(fixed_out - dyn_out).max()):.2e}")
batched = run_once(dyn_session, fixed_input(8))
check("動的バッチのモデルは 8 件まとめて処理できる",
      batched.shape == (8, 6)
      and bool(np.allclose(batched.sum(axis=1), 1.0, atol=1e-4)),
      f"出力の形 {tuple(batched.shape)} / 各行の合計は 1")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション13の検証はすべて成功しました"
      "（絶対値ではなく関係だけを検証しています）。")
