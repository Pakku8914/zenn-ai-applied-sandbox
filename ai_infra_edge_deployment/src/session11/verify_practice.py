#!/usr/bin/env python3
"""セッション11の練習問題の解答を自己検証する（計算問題だけ）。

    python src/session11/verify_practice.py

検証するのは**決定的な算術**（問題2・3・4・6・7・8）だけである。
問題1・5・9・10 は記述問題なので、ここでは扱わない。記述問題の採点基準は
「向きと理由が説明できているか」であり、固定値の一致ではない。

数値の3分類は edge_budget.py の冒頭と同じ規律で扱う。混ぜてはいけない。

  ① 実測値   : reports/ の測定結果（測定条件つきで引用する）
  ② 物理計算 : 定数から計算できるもの（往復の物理的下限）
  ③ 前提値   : 読者が自分の環境の値を入れるもの（端末のメモリ・台数・回線）
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from edge_budget import (  # noqa: E402
    GB, MB, Footprint, MemoryBudget, fits, kv_mb, max_bytes_per_param,
    monthly_upload_gb, rtt_floor_ms,
)

# ① 引用してよい実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
#    Python 3.12.13 / llama.cpp -t 2）。ここでは比較の相手として使うだけ。
Q4_K_M_MB = 379.4          # models/gguf/qwen05b-q4_k_m.gguf の実サイズ
F16_MB = 948.1             # 同 f16
ONNX_FP32_MB = 70.13       # エッジの分類器（ONNX fp32）
ONNX_INT8_MB = 17.56       # 同 int8（動的量子化）
TTFT_P50_MS = 61.0         # Q8_0・スロット1・並列1 の TTFT p50
TPOT_P50_MS = 14.63        # 同じ条件の TPOT p50

# ③ 前提値（練習問題で与えた4つの端末。自分の端末の値に置き換えて使う）
DEVICES = {
    "A": MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536),
    "B": MemoryBudget(total_mb=2048, os_reserved_mb=768, other_apps_mb=512),
    "C": MemoryBudget(total_mb=8192, os_reserved_mb=1024, other_apps_mb=1024),
    "D": MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128),
}
RUNTIME_MB = 150.0      # ③ 言語モデルの実行時の作業メモリ
CLASSIFIER_RUNTIME_MB = 50.0  # ③ 分類器だけを動かす場合の実行時メモリ
SEQ_LEN = 2048          # ③ 想定する系列長
SLO_MS = 100.0          # ③ 一次応答の SLO（サービスレベル目標）
DEVICE_COUNT = 1000     # ③ OTA（無線経由の更新）で配る端末数
LINE_MBPS = 100.0       # ③ 配布に使える回線（専有できたと仮定）

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def verdict(bytes_per_param: float) -> str:
    """逆算した値から、必要な量子化の強さを言葉にする（本文の表と同じ区切り）。"""
    if bytes_per_param >= 2.0:
        return "f16 のまま載る"
    if bytes_per_param >= 1.0:
        return "8bit 相当が必要"
    if bytes_per_param >= 0.5:
        return "4bit 相当が必要"
    if bytes_per_param >= 0.125:
        return "極端な量子化が必要"
    return "載せられない"


print("=== セッション11：練習問題の答え合わせ（計算問題のみ）===")

# --- 問題2：往復の物理的下限 -------------------------------------------------
print("\n[問題2] 往復の物理的下限（②物理計算・光ファイバ 200,000 km/s。実測ではない）")
print(f"| 距離 | 往復の下限 | SLO {SLO_MS:.0f}ms のうち | TPOT {TPOT_P50_MS}ms の何トークン分 |")
print("| :--- | --: | --: | --: |")
for label, km in (("エッジ（端末内・0 km）", 0), ("同一都市（50 km）", 50),
                  ("同一地域（300 km）", 300), ("国内（1,000 km）", 1000),
                  ("大陸間（8,000 km）", 8000), ("地球半周（16,000 km）", 16000)):
    ms = rtt_floor_ms(km)
    print(f"| {label} | {ms:.1f} ms | {ms / SLO_MS * 100:.1f}% | {ms / TPOT_P50_MS:.1f} |")

far, half = rtt_floor_ms(8000), rtt_floor_ms(16000)
check("問題2 距離0で 0.0 ms、1,000 km で 10.0 ms",
      rtt_floor_ms(0) == 0.0 and abs(rtt_floor_ms(1000) - 10.0) < 1e-9,
      "エッジでは往復が消える")
check("問題2 距離を2倍にすると下限も2倍",
      abs(rtt_floor_ms(2000) - rtt_floor_ms(1000) * 2) < 1e-9,
      f"{rtt_floor_ms(1000):.1f} ms -> {rtt_floor_ms(2000):.1f} ms")
check(f"問題2 大陸間の下限 {far:.1f} ms は TTFT p50 {TTFT_P50_MS:.0f} ms（①実測）を上回る",
      far > TTFT_P50_MS)
check("問題2 地球半周は下限だけで SLO 100 ms を超える", half > SLO_MS,
      f"{half:.1f} ms（予算の {half / SLO_MS * 100:.1f}%）")
check(f"問題2 大陸間の下限は TPOT p50 {TPOT_P50_MS} ms（①実測）の5トークン分以上",
      far / TPOT_P50_MS >= 5.0, f"{far / TPOT_P50_MS:.1f} トークン分")

# --- 問題3：載るかどうか -----------------------------------------------------
kv2048 = kv_mb("qwen05b", SEQ_LEN)
gen_fp = Footprint(weights_mb=Q4_K_M_MB, kv_mb=kv2048, runtime_mb=RUNTIME_MB)

print(f"\n[問題3] 0.5B級 Q4_K_M が端末に載るか"
      f"（系列長 {SEQ_LEN}・実行時 {RUNTIME_MB:.1f} MB ③前提値）")
print(f"フットプリント: {gen_fp.total_mb:.1f} MB"
      f"（重み {gen_fp.weights_mb:.1f} ①実測 ＋ KVキャッシュ {gen_fp.kv_mb:.1f}"
      f" ＋ 実行時 {gen_fp.runtime_mb:.1f} ③前提値）")
print("| 端末 | 物理 | 使えるメモリ | 上限（余白20%） | 判定 | 余白 |")
print("| :--- | --: | --: | --: | :--- | --: |")
placement = {}
for name in ("A", "B", "C", "D"):
    budget = DEVICES[name]
    ok, slack = fits(budget, gen_fp)
    placement[name] = (ok, slack)
    print(f"| 端末{name} | {budget.total_mb:.0f} MB | {budget.available_mb:.1f} MB | "
          f"{budget.limit_mb:.1f} MB | {'載る' if ok else '載らない'} | {slack:+.1f} MB |")

print("\n端末B で系列長を伸ばしたとき（重みと実行時は同じ）")
sweep = {}
for seq in (1024, 2048, 4096, 8192):
    fp_seq = Footprint(Q4_K_M_MB, kv_mb("qwen05b", seq), RUNTIME_MB)
    ok, slack = fits(DEVICES["B"], fp_seq)
    sweep[seq] = (ok, slack)
    print(f"系列長 {seq}: KV {fp_seq.kv_mb:.1f} MB / 合計 {fp_seq.total_mb:.1f} MB → "
          f"{'載る' if ok else '載らない'}（余白 {slack:+.1f} MB）")

no_kv = Footprint(Q4_K_M_MB, 0.0, RUNTIME_MB)
ok_no_kv, slack_no_kv = fits(DEVICES["D"], no_kv)
print(f"端末D は KVキャッシュを 0 にしても 合計 {no_kv.total_mb:.1f} MB → "
      f"{'載る' if ok_no_kv else '載らない'}（余白 {slack_no_kv:+.1f} MB）")

check("問題3 フットプリントの合計は 553.4 MB", abs(gen_fp.total_mb - 553.4) < 0.05,
      f"重みが {gen_fp.weights_mb / gen_fp.total_mb:.1%} を占める")
check("問題3 端末A・B・C は載り、端末D は載らない",
      tuple(placement[n][0] for n in "ABCD") == (True, True, True, False),
      f"端末D は {abs(placement['D'][1]):.1f} MB 超過")
check("問題3 端末B の余白は 61.0 MB しかない", abs(placement["B"][1] - 61.0) < 0.05,
      "他アプリが 100 MB 増えれば破綻する")
check("問題3 端末B は系列長 4096 まで載り、8192 で超過する",
      sweep[4096][0] and not sweep[8192][0],
      f"8192 で {abs(sweep[8192][1]):.1f} MB 超過")
check("問題3 端末D は KVキャッシュ 0 でも載らない（重みが支配的）", not ok_no_kv,
      f"{no_kv.total_mb:.1f} MB / 上限 {DEVICES['D'].limit_mb:.1f} MB")

# --- 問題4：ストレージとモデル更新の帯域 -------------------------------------
two_gen_q4 = Q4_K_M_MB * 2
two_gen_f16 = F16_MB * 2
ota_q4_gb = Q4_K_M_MB * DEVICE_COUNT * MB / GB
ota_fp32_gb = ONNX_FP32_MB * DEVICE_COUNT * MB / GB
ota_int8_gb = ONNX_INT8_MB * DEVICE_COUNT * MB / GB
seconds = Q4_K_M_MB * DEVICE_COUNT * 8 / LINE_MBPS

print(f"\n[問題4] ストレージとモデル更新の帯域"
      f"（③前提値：端末 {DEVICE_COUNT} 台・回線 {LINE_MBPS:.0f} Mbps を専有）")
print(f"2世代ぶんのストレージ: Q4_K_M {two_gen_q4:.1f} MB / f16 {two_gen_f16:.1f} MB")
print(f"1回の配布（{DEVICE_COUNT} 台）: Q4_K_M {ota_q4_gb:.1f} GB / "
      f"ONNX fp32 {ota_fp32_gb:.1f} GB / ONNX int8 {ota_int8_gb:.1f} GB")
print(f"年12回の配布: Q4_K_M {ota_q4_gb * 12:.1f} GB/年")
print(f"1回の配布にかかる時間: {seconds / 3600:.1f} 時間（{seconds:,.0f} 秒）")

check("問題4 2世代ぶんは Q4_K_M で 758.8 MB", abs(two_gen_q4 - 758.8) < 0.05,
      f"f16 なら {two_gen_f16:.1f} MB＝{two_gen_f16 * MB / GB:.2f} GB")
check(f"問題4 {DEVICE_COUNT} 台への1回の配布は 370.5 GB", abs(ota_q4_gb - 370.5) < 0.05,
      "推論をやめても通信は残る")
check("問題4 int8 は fp32 の 25.0%＝配布量も 4 分の1になる",
      abs(ONNX_INT8_MB / ONNX_FP32_MB - 0.25) < 0.005,
      f"{ONNX_INT8_MB / ONNX_FP32_MB:.1%}（{ota_fp32_gb:.1f} GB -> {ota_int8_gb:.1f} GB）")
check("問題4 1回の配布に 8 時間以上かかる", seconds / 3600 > 8.0,
      f"{seconds / 3600:.1f} 時間。更新頻度の上限は回線が決める")

# --- 問題6：逆算 -------------------------------------------------------------
kv_big = kv_mb("llama8b", SEQ_LEN)
q4_bpp = Q4_K_M_MB * MB / 5e8

print(f"\n[問題6] 逆算：1パラメータに使えるバイト数"
      f"（系列長 {SEQ_LEN}・実行時 {RUNTIME_MB:.1f} MB ③前提値）")
print("| 端末 | 上限 | 0.5B級（5億） | 判定 | 8B級（80億） | 判定 |")
print("| :--- | --: | --: | :--- | --: | :--- |")
bpp = {}
for name in ("A", "B", "C", "D"):
    budget = DEVICES[name]
    small = max_bytes_per_param(budget, 5e8, kv2048, RUNTIME_MB)
    big = max_bytes_per_param(budget, 8e9, kv_big, RUNTIME_MB)
    bpp[name] = (small, big)
    print(f"| 端末{name} | {budget.limit_mb:.1f} MB | {small:.3f} | {verdict(small)} | "
          f"{big:.3f} | {verdict(big)} |")
print(f"参考: Q4_K_M（①実測 {Q4_K_M_MB} MB）は {q4_bpp:.3f} バイト/パラメータ相当")
short = [f"端末{n}（0.5B級 {v[0]:.3f}）" for n, v in bpp.items() if v[0] < q4_bpp]
short += [f"端末{n}（8B級 {v[1]:.3f}）" for n, v in bpp.items() if 0.125 <= v[1] < q4_bpp]
print("Q4_K_M でも載らない: " + " / ".join(short))
bpp_c_short = max_bytes_per_param(DEVICES["C"], 8e9, kv_mb("llama8b", 1024), RUNTIME_MB)
print(f"端末C・8B級は系列長を 1024 に半減しても {bpp_c_short:.3f} バイト/パラメータ"
      f"（Q4_K_M の {q4_bpp:.3f} に届かない）")

check("問題6 端末A・C の 0.5B級は f16（2.0 バイト）でも載る",
      bpp["A"][0] >= 2.0 and bpp["C"][0] >= 2.0,
      f"A {bpp['A'][0]:.3f} / C {bpp['C'][0]:.3f}")
check("問題6 端末B・D の 0.5B級は 4bit 相当が必要",
      0.5 <= bpp["B"][0] < 1.0 and 0.5 <= bpp["D"][0] < 1.0,
      f"B {bpp['B'][0]:.3f} / D {bpp['D'][0]:.3f}")
check("問題6 端末D は Q4_K_M でも 0.5B級が載らない", bpp["D"][0] < q4_bpp,
      f"{bpp['D'][0]:.3f} < {q4_bpp:.3f}")
check("問題6 8B級は端末A・B・D で 1bit（0.125 バイト）未満＝載せられない",
      all(bpp[n][1] < 0.125 for n in "ABD"),
      f"A {bpp['A'][1]:.3f} / B {bpp['B'][1]:.3f} / D {bpp['D'][1]:.3f}")
check("問題6 端末C だけ 8B級に望みがあるが Q4_K_M では足りない",
      0.5 <= bpp["C"][1] < q4_bpp, f"{bpp['C'][1]:.3f}（{verdict(bpp['C'][1])}）")
check("問題6 端末C の 8B級は系列長を半減しても Q4_K_M に届かない", bpp_c_short < q4_bpp,
      f"{bpp_c_short:.3f} < {q4_bpp:.3f}")

# --- 問題7：送信率と通信量 ---------------------------------------------------
payload, per_hour, devices = 200 * 1024, 60, 50
base_gb = monthly_upload_gb(payload, per_hour=per_hour, devices=devices)

print(f"\n[問題7] 送信率と月間の通信量"
      f"（③前提値：画像 200 KB を毎分・{devices} 台・24 時間・30 日）")
print("| 送信率 | 上りの月間転送量 | 全部送る場合との比 |")
print("| --: | --: | --: |")
uploads = {}
for ratio in (1.0, 0.2, 0.05, 0.01):
    gb = monthly_upload_gb(payload, per_hour=per_hour, devices=devices, send_ratio=ratio)
    uploads[ratio] = gb
    print(f"| {ratio:.0%} | {gb:.1f} GB/月 | {base_gb / gb:.1f} 分の1 |")

ota_month_gb = Q4_K_M_MB * devices * MB / GB          # 月1回の配布（下り）
telemetry_gb = 1.0 * devices * 30 * MB / GB           # 1台 1 MB/日 のテレメトリ（上り）
rest_gb = ota_month_gb + telemetry_gb
print(f"エッジ化しても残る通信（③前提値：Q4_K_M を月1回・{devices} 台"
      f"＋テレメトリ 1 MB/台/日）")
print(f"モデル配布（下り）{ota_month_gb:.1f} GB/月 ＋ テレメトリ（上り）"
      f"{telemetry_gb:.1f} GB/月 = {rest_gb:.1f} GB/月")

check("問題7 送信率 5% で上りは 20.0 分の1になる",
      abs(base_gb / uploads[0.05] - 20.0) < 0.01,
      f"{base_gb:.1f}GB -> {uploads[0.05]:.1f}GB")
check("問題7 転送量は送信率に比例する（1% なら 100 分の1）",
      abs(base_gb / uploads[0.01] - 100.0) < 0.05, f"{uploads[0.01]:.1f} GB/月")
check("問題7 エッジ化しても通信は残る", rest_gb > 0 and abs(rest_gb - 20.0) < 0.1,
      f"この前提では {rest_gb:.1f} GB/月（うち配布 {ota_month_gb:.1f} GB）")
check("問題7 残る通信は送信率 5% の上りと同じ桁",
      0.5 < rest_gb / uploads[0.05] < 2.0,
      f"{rest_gb:.1f} GB/月 と {uploads[0.05]:.1f} GB/月")

# --- 問題8：エッジに残すタスクのフットプリント -------------------------------
classifier = Footprint(weights_mb=ONNX_INT8_MB * 2, kv_mb=0.0,
                       runtime_mb=CLASSIFIER_RUNTIME_MB)
print(f"\n[問題8] エッジに残すタスクのフットプリント"
      f"（①実測 ONNX int8 {ONNX_INT8_MB} MB × 2本"
      f"・実行時 {CLASSIFIER_RUNTIME_MB:.1f} MB ③前提値）")
print(f"分類器2本の合計: {classifier.total_mb:.2f} MB")
light = {}
for name in ("A", "D"):
    ok, slack = fits(DEVICES[name], classifier)
    light[name] = (ok, slack)
    print(f"端末{name}: 上限 {DEVICES[name].limit_mb:.1f} MB → "
          f"{'載る' if ok else '載らない'}（余白 {slack:+.1f} MB）")
print(f"参考: 端末D に 0.5B級 Q4_K_M（{gen_fp.total_mb:.1f} MB）を置くと"
      f"載らない（{placement['D'][1]:+.1f} MB）")

check("問題8 分類器2本なら端末D にも載る", light["D"][0], f"余白 {light['D'][1]:.1f} MB")
check("問題8 回答生成（0.5B級 Q4_K_M）は端末D に載らない", not placement["D"][0],
      f"{abs(placement['D'][1]):.1f} MB 超過")
check("問題8 分類器のフットプリントは 0.5B級の 6 分の1未満",
      classifier.total_mb / gen_fp.total_mb < 1 / 6,
      f"{classifier.total_mb / gen_fp.total_mb:.1%}"
      f"（{classifier.total_mb:.2f} MB / {gen_fp.total_mb:.1f} MB）")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print(f"\nセッション11の練習問題の検証はすべて成功しました（{checked} 件）。")
