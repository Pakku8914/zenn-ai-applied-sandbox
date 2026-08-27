#!/usr/bin/env python3
"""セッション3の練習問題の解答を自己検証する。

問題1・2・4・6・7・8 の数値が解答章の値と一致することを確かめる。
サーバを使わないので数秒で終わる。期待値と違えば非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from batching_sim import average, continuous_batch, static_batch  # noqa: E402
from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent  # noqa: E402
from kv_budget import rows  # noqa: E402

GB = 1024 ** 3
QWEN = {k: v for k, v in QWEN_05B.items() if k != "hidden"}
BIG = {k: v for k, v in LLAMA_8B.items() if k != "hidden"}

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 問題1：仮の構成（層32・KVヘッド4・ヘッド次元128・f16）--------------------
p1 = kv_cache_bytes(32, 4, 128, seq_len=1, batch=1)
check("問題1 1トークンあたり 65,536 バイト", p1.per_token_bytes == 65536,
      f"{p1.per_token_bytes} バイト（{p1.per_token_kb:.2f} KB）")
p1b = kv_cache_bytes(32, 4, 128, seq_len=4096, batch=1)
check("問題1 系列長4096で 256.0 MB", round(p1b.total_mb, 1) == 256.0, f"{p1b.total_mb:.1f} MB")
p1c = kv_cache_bytes(32, 8, 128, seq_len=1, batch=1)
check("問題1 KVヘッドを8にすると 131,072 バイト", p1c.per_token_bytes == 131072,
      f"{p1c.per_token_bytes} バイト")
p1d = kv_cache_bytes(32, 4, 128, seq_len=4096, batch=1, bytes_per_elem=1)
check("問題1 1バイト型なら 128.0 MB", round(p1d.total_mb, 1) == 128.0, f"{p1d.total_mb:.1f} MB")

# --- 問題2：実測ツールの表との突き合わせ --------------------------------------
p2a = kv_cache_bytes(**QWEN, seq_len=2048, batch=4)
p2b = kv_cache_bytes(**BIG, seq_len=2048, batch=4)
check("問題2 0.5B・2048・並列4 は 96.0 MB", round(p2a.total_mb, 1) == 96.0,
      f"{p2a.total_mb:.1f} MB")
check("問題2 8B級・2048・並列4 は 1024.0 MB", round(p2b.total_mb, 1) == 1024.0,
      f"{p2b.total_mb:.1f} MB")

# --- 問題4：-c 6144 -np 3 -----------------------------------------------------
check("問題4 -c 6144 -np 3 は1スロット 2048", 6144 // 3 == 2048)
p4 = kv_cache_bytes(**QWEN, seq_len=6144, batch=1)
check("問題4 -c 6144 の確保量は 72.0 MB", round(p4.total_mb, 1) == 72.0, f"{p4.total_mb:.1f} MB")

# --- 問題6：KVキャッシュ予算 1.5GB からの逆算 ---------------------------------
budget = int(1.5 * GB)
n6a = max_concurrent(budget, 4096, **QWEN)
n6b = max_concurrent(budget, 1024, **QWEN)
n6c = max_concurrent(budget, 4096, bytes_per_elem=1, **QWEN)
check("問題6 系列長4096・f16 は 32 本", n6a == 32, f"{n6a} 本")
check("問題6 系列長1024・f16 は 128 本", n6b == 128, f"{n6b} 本")
check("問題6 系列長4096・1バイト型は 64 本", n6c == 64, f"{n6c} 本")

# --- 問題7：静的バッチと連続バッチ --------------------------------------------
jobs = [("A", 12), ("B", 2), ("C", 6), ("D", 10)]
st, co = static_batch(jobs, 2), continuous_batch(jobs, 2)
check("問題7 静的バッチの平均完了は 17.0", average(st.values()) == 17.0, str(st))
check("問題7 連続バッチの平均完了は 10.0", average(co.values()) == 10.0, str(co))
check("問題7 最後の完了は 22 → 18", (max(st.values()), max(co.values())) == (22, 18))
st3, co3 = static_batch(jobs, 3), continuous_batch(jobs, 3)
check("問題7 スロット3にすると 14.5 → 8.0",
      (average(st3.values()), average(co3.values())) == (14.5, 8.0))
check("問題7 必要ステップの合計は方式によらず同じ",
      sum(s for _, s in jobs) == 30, "30 ステップ")

# --- 問題8：16GB の容量計画 ---------------------------------------------------
kv_budget = int(16.0 * GB) - int(5.0 * GB) - int(1.5 * GB)
check("問題8 KVキャッシュに使えるのは 9.5GB", kv_budget == int(9.5 * GB),
      f"{kv_budget / GB:.2f} GB")
n_f16 = [n for _, _, n in rows("llama8b", kv_budget, 2)]
n_q8 = [n for _, _, n in rows("llama8b", kv_budget, 1)]
check("問題8 f16 の本数は [76, 38, 19, 9]", n_f16 == [76, 38, 19, 9], str(n_f16))
check("問題8 1バイト型の本数は [152, 76, 38, 19]", n_q8 == [152, 76, 38, 19], str(n_q8))
check("問題8 同時16本を満たす系列長の上限は 4096",
      max(seq for seq, _, n in rows("llama8b", kv_budget, 2) if n >= 16) == 4096)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3の練習問題の検証はすべて成功しました。")
