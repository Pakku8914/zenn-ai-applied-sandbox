#!/usr/bin/env python3
"""セッション11の自己検証：見積もり計算が正しいこと。

この章は「どこで推論するか」を決める章なので、検証するのは**見積もりの算術**である。
サーバもモデルも要らないので、ネットワークなしで数秒で終わる。

  python src/session11/verify.py

**期待値に絶対値を書いてよいのは、決定的な算術だけ**である。
レイテンシの実測値（TTFT・TPOT）は実行ごとにぶれるのでこのファイルでは測らない。
実測値は「① 引用してよい定数」として比較の相手に使うだけにしている。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edge_budget import (  # noqa: E402
    MB, Footprint, MemoryBudget, fits, kv_mb, max_bytes_per_param, monthly_upload_gb,
    rtt_floor_ms, shape, weights_mb,
)
from infrakit.cost import SelfHosted  # noqa: E402
from infrakit.kvcache import kv_cache_bytes, max_concurrent  # noqa: E402

# ① 引用してよい実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
#    Python 3.12.13 / llama.cpp -t 2）。ここでは比較の相手として使うだけ。
Q4_K_M_WEIGHTS_MB = 379.4      # models/gguf/qwen05b-q4_k_m.gguf の実サイズ
TTFT_P50_Q8_MS = 61.0          # Q8_0・スロット1・並列1 の TTFT p50
TPOT_P50_Q8_MS = 14.63         # 同じ条件の TPOT p50
RPS_PER_INSTANCE = 1.15        # Q4_K_M・スロット2・並列4 の rps

# ③ 前提値（読者が自分の端末の値に置き換える）
DEVICE = MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536, headroom=0.2)
RUNTIME_MB = 150.0
SEQ_LEN, BATCH = 2048, 1

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print("=== セッション11：エッジに載るかの見積もり ===")

# --- [1] メモリ予算 ---------------------------------------------------------
print(f"\n[1] メモリ予算（③前提値：端末 {DEVICE.total_mb:.0f} MB / "
      f"OS {DEVICE.os_reserved_mb:.0f} MB / 他アプリ {DEVICE.other_apps_mb:.0f} MB / "
      f"余白 {DEVICE.headroom:.0%}）")
print(f"使えるメモリ: {DEVICE.available_mb:.1f} MB")
print(f"余白を残した上限: {DEVICE.limit_mb:.1f} MB")

# --- [2] KVキャッシュ -------------------------------------------------------
small = kv_cache_bytes(seq_len=1, batch=1, **shape("qwen05b"))
big = kv_cache_bytes(seq_len=1, batch=1, **shape("llama8b"))
kv_small = kv_mb("qwen05b", SEQ_LEN, BATCH)
kv_big = kv_mb("llama8b", SEQ_LEN, BATCH)
n_small = max_concurrent(1024 ** 3, SEQ_LEN, **shape("qwen05b"))
n_big = max_concurrent(1024 ** 3, SEQ_LEN, **shape("llama8b"))

print("\n[2] KVキャッシュ（セッション3の式）")
print(f"0.5B級の1トークンあたり: {small.per_token_bytes:,} バイト（{small.per_token_kb:.2f} KB）")
print(f"8B級の1トークンあたり: {big.per_token_bytes:,} バイト（{big.per_token_kb:.2f} KB）")
print(f"系列長 {SEQ_LEN}・同時{BATCH} の KVキャッシュ: "
      f"0.5B級 {kv_small:.1f} MB / 8B級 {kv_big:.1f} MB")
print(f"1GB を KVキャッシュに使えるとき持てる本数: 0.5B級 {n_small} 本 / 8B級 {n_big} 本")
check("0.5B級の1トークンあたりが 12,288 バイト", small.per_token_bytes == 12_288,
      f"{small.per_token_kb:.2f} KB")
check("8B級の1トークンあたりが 131,072 バイト", big.per_token_bytes == 131_072,
      f"{big.per_token_kb:.2f} KB")
check("1GB で持てる本数が 0.5B級 42 本 / 8B級 4 本", (n_small, n_big) == (42, 4),
      "セッション3の実測表と一致")
check("系列長を2倍にすると KVキャッシュも2倍",
      abs(kv_mb("qwen05b", 2048) - kv_mb("qwen05b", 1024) * 2) < 1e-9,
      f"{kv_mb('qwen05b', 1024):.1f}MB -> {kv_mb('qwen05b', 2048):.1f}MB")

# --- [3] 載るか -------------------------------------------------------------
edge_fp = Footprint(weights_mb=Q4_K_M_WEIGHTS_MB, kv_mb=kv_small, runtime_mb=RUNTIME_MB)
ok_edge, slack_edge = fits(DEVICE, edge_fp)

print(f"\n[3] 載るか（0.5B級 Q4_K_M・系列長 {SEQ_LEN}・同時{BATCH}）")
print(f"重み（①実測 {Q4_K_M_WEIGHTS_MB} MB）: {edge_fp.weights_mb:.1f} MB")
print(f"KVキャッシュ: {edge_fp.kv_mb:.1f} MB")
print(f"実行時の作業メモリ（③前提値）: {edge_fp.runtime_mb:.1f} MB")
print(f"合計: {edge_fp.total_mb:.1f} MB / 上限 {DEVICE.limit_mb:.1f} MB")
check("0.5B級 Q4_K_M はこの端末に収まる", ok_edge, f"余白 {slack_edge:.1f} MB")
check("0.5B級では重みが合計の半分以上を占める",
      edge_fp.weights_mb / edge_fp.total_mb > 0.5,
      f"{edge_fp.weights_mb / edge_fp.total_mb:.1%}")

# --- [4] 載らない例 ---------------------------------------------------------
big_fp = Footprint(weights_mb=weights_mb(8e9, 2), kv_mb=kv_big, runtime_mb=RUNTIME_MB)
print(f"\n[4] 載らない例（8B級 f16・系列長 {SEQ_LEN}・同時{BATCH}）")
print(f"重み: {big_fp.weights_mb:.1f} MB")
print(f"KVキャッシュ: {big_fp.kv_mb:.1f} MB")
print(f"実行時の作業メモリ（③前提値）: {big_fp.runtime_mb:.1f} MB")
print(f"合計: {big_fp.total_mb:.1f} MB / 上限 {DEVICE.limit_mb:.1f} MB")
check("8B級 f16 はこの端末に収まらない", big_fp.total_mb > DEVICE.limit_mb,
      f"上限の {big_fp.total_mb / DEVICE.limit_mb:.1f} 倍")

# --- [5] 逆算 ---------------------------------------------------------------
bpp_small = max_bytes_per_param(DEVICE, 5e8, kv_small, RUNTIME_MB)
bpp_big = max_bytes_per_param(DEVICE, 8e9, kv_big, RUNTIME_MB)
q4_bpp = Q4_K_M_WEIGHTS_MB * MB / 5e8

print("\n[5] 逆算（この予算に載せるには1パラメータ何バイトまで使えるか）")
print(f"0.5B級（5億パラメータ）: {bpp_small:.3f} バイト/パラメータ")
print(f"8B級（80億パラメータ）: {bpp_big:.3f} バイト/パラメータ")
print(f"参考: Q4_K_M の {Q4_K_M_WEIGHTS_MB} MB は {q4_bpp:.3f} "
      "バイト/パラメータに相当（①実測サイズから計算）")
check("0.5B級は f16（2.0 バイト）でも収まる", bpp_small >= 2.0,
      f"{bpp_small:.3f} バイト/パラメータ")
check("8B級は 1bit（0.125 バイト）未満しか使えない＝載せられない", bpp_big < 0.125,
      f"{bpp_big:.3f} バイト/パラメータ")

# --- [6] 通信量 -------------------------------------------------------------
all_gb = monthly_upload_gb(200 * 1024, per_hour=60, devices=50)
filtered_gb = monthly_upload_gb(200 * 1024, per_hour=60, devices=50, send_ratio=0.05)
print("\n[6] 通信量（③前提値：画像 200 KB を毎分・50 台・24 時間・30 日）")
print(f"すべてクラウドへ送る: {all_gb:.1f} GB/月")
print(f"エッジで一次判定して 5% だけ送る: {filtered_gb:.1f} GB/月")
check("前段をエッジにすると月間転送量が 20.0 分の1になる",
      abs(all_gb / filtered_gb - 20.0) < 0.01,
      f"{all_gb:.1f}GB -> {filtered_gb:.1f}GB")

# --- [7] 往復レイテンシの物理的下限 -----------------------------------------
print("\n[7] 往復レイテンシの物理的下限（②物理計算・光ファイバ 200,000 km/s。実測ではない）")
for label, km in (("エッジ（端末内・距離 0 km）", 0), ("同一都市（50 km）", 50),
                  ("国内（1,000 km）", 1000), ("大陸間（8,000 km）", 8000)):
    print(f"{label}: {rtt_floor_ms(km):.1f} ms")
far = rtt_floor_ms(8000)
check("エッジの下限は 0 ms、1,000 km は 10.0 ms",
      rtt_floor_ms(0) == 0.0 and abs(rtt_floor_ms(1000) - 10.0) < 0.01)
check(f"大陸間の下限 {far:.1f} ms は Q8_0 の TTFT p50 {TTFT_P50_Q8_MS:.0f} ms（①実測）を上回る",
      far > TTFT_P50_Q8_MS)
check(f"大陸間の下限は TPOT p50 {TPOT_P50_Q8_MS} ms（①実測）の 5 トークン分以上",
      far / TPOT_P50_Q8_MS >= 5.0, f"{far / TPOT_P50_Q8_MS:.1f} トークン分")

# --- [8] 単位コストの出方 ---------------------------------------------------
low = SelfHosted(hourly_cost=1.0, instances=1, rps_per_instance=RPS_PER_INSTANCE,
                 utilization=0.1)
high = SelfHosted(hourly_cost=1.0, instances=1, rps_per_instance=RPS_PER_INSTANCE,
                  utilization=0.9)
print("\n[8] 単位コストの出方（infrakit.cost・時間単価を 1 と置いた相対比較）")
print(f"利用率 10%: {low.requests_per_hour:.0f} リクエスト/時 → "
      f"1000リクエスト単価 {low.cost_per_1k_requests:.4f}")
print(f"利用率 90%: {high.requests_per_hour:.0f} リクエスト/時 → "
      f"1000リクエスト単価 {high.cost_per_1k_requests:.4f}")
ratio = low.cost_per_1k_requests / high.cost_per_1k_requests
check("利用率が 9 倍になると単価は 9 分の1になる", abs(ratio - 9.0) < 0.01,
      f"{ratio:.1f} 分の1")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print(f"\nセッション11の検証はすべて成功しました（{checked} 件）。")
