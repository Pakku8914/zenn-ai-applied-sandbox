#!/usr/bin/env python3
"""セッション3の自己検証：KVキャッシュの計算が正しいこと。

サーバを使わないので数秒で終わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 手計算と一致すること ---------------------------------------------------
# 層 24 × KVヘッド 2 × ヘッド次元 64 × 2(K,V) × 2バイト = 12,288 バイト/トークン
est = kv_cache_bytes(24, 2, 64, seq_len=1, batch=1)
check("1トークンあたりが手計算と一致", est.per_token_bytes == 24 * 2 * 64 * 2 * 2,
      f"{est.per_token_bytes} バイト（{est.per_token_kb:.2f} KB）")

# 系列長と同時実行数に比例すること
a = kv_cache_bytes(24, 2, 64, seq_len=1024, batch=1)
b = kv_cache_bytes(24, 2, 64, seq_len=2048, batch=1)
c = kv_cache_bytes(24, 2, 64, seq_len=1024, batch=2)
check("系列長を2倍にすると2倍になる", b.total_bytes == a.total_bytes * 2,
      f"{a.total_mb:.1f}MB -> {b.total_mb:.1f}MB")
check("同時実行数を2倍にすると2倍になる", c.total_bytes == a.total_bytes * 2,
      f"{a.total_mb:.1f}MB -> {c.total_mb:.1f}MB")

# 型を変えると比例して減ること（KVキャッシュの量子化）
half = kv_cache_bytes(24, 2, 64, seq_len=1024, batch=1, bytes_per_elem=1)
check("1バイト型にすると半分になる", half.total_bytes == a.total_bytes // 2,
      f"{a.total_mb:.1f}MB -> {half.total_mb:.1f}MB")

# --- モデル規模の差 ---------------------------------------------------------
small = kv_cache_bytes(**{k: v for k, v in QWEN_05B.items() if k != "hidden"},
                       seq_len=2048, batch=1)
big = kv_cache_bytes(**{k: v for k, v in LLAMA_8B.items() if k != "hidden"},
                     seq_len=2048, batch=1)
check("8B級は 0.5B より KVキャッシュが大きい", big.total_bytes > small.total_bytes * 5,
      f"{small.total_mb:.1f}MB vs {big.total_mb:.1f}MB "
      f"（{big.total_bytes / small.total_bytes:.0f}倍）")

# --- 与えられたメモリで持てる同時実行数 -------------------------------------
n_small = max_concurrent(1024**3, 2048, **{k: v for k, v in QWEN_05B.items() if k != "hidden"})
n_big = max_concurrent(1024**3, 2048, **{k: v for k, v in LLAMA_8B.items() if k != "hidden"})
check("1GB で 0.5B は 10 本以上持てる", n_small >= 10, f"{n_small} 本")
check("1GB で 8B級は 0.5B より少ない", n_big < n_small, f"{n_big} 本 vs {n_small} 本")
print(f"\n1GB のメモリで系列長 2048 を持てる本数: 0.5B={n_small} / 8B級={n_big}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3の検証はすべて成功しました。")
