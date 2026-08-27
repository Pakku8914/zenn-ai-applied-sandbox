#!/usr/bin/env python3
"""セッション14の自己検証：数百KBの端末に載るかの判断が正しいこと。

  python src/session14/verify.py

**この章で検証するのは決定的な計算だけ**である。マイコンの実機は持っていないので、
推論時間・消費電力は測らないし、期待値にも書かない。検証するのは次の3種類。

  ① 枠の算術       : 2つの池（Flash / RAM）の上限
  ② 逆算           : 1パラメータに使えるバイト数（0.125 を下回るか）
  ③ 判定の分かれ方 : 数え方・型・const・演算子で「載る／載らない」が変わること

サーバもモデルファイルもネットワークも要らないので、数秒で終わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(SANDBOX / "src" / "session11"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from c_array import (  # noqa: E402
    DEMO_FP32, demo_int8, emit_c_array, flash_bytes, quantize_symmetric,
    ram_copy_kb, source_bounds, source_bytes,
)
from edge_budget import monthly_upload_gb  # noqa: E402
from feasibility import (  # noqa: E402
    DEVICE_A, DEVICE_D, TASKS, mb_ok, mcu_ok,
)
from mcu_budget import (  # noqa: E402
    C12_PARAMS, DEVICE_E, GGUF_Q4_K_M_MB, KB, KV_PER_TOKEN_KB_05B, KV_PER_TOKEN_KB_8B,
    MODEL_C12, MODEL_K, MODEL_V, MODEL_W, ONNX_INT8_MB, SEQ_LEN,
    bytes_per_param_needed, fits, fits_raw, kv_tokens, max_params,
)
from op_support import GRAPHS, SUPPORTED, advice, check_ops  # noqa: E402

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print("=== セッション14：数百KBの端末に載るかの判断 ===")

# --- [1] 2つの池 -------------------------------------------------------------
b = DEVICE_E
print(f"\n[1] 端末E の枠（③前提値：RAM {b.ram_kb:.0f} KB / Flash {b.flash_kb:.0f} KB / "
      f"余白 {b.headroom:.0%}）")
print(f"RAM: 使える {b.ram_available_kb:.2f} KB -> アリーナ上限 {b.arena_limit_kb:.2f} KB")
print(f"Flash: 使える {b.flash_available_kb:.2f} KB -> 重みの上限 {b.weights_limit_kb:.2f} KB")
check("RAM の内訳が 208.00 KB -> 上限 166.40 KB",
      abs(b.ram_available_kb - 208.0) < 1e-9 and abs(b.arena_limit_kb - 166.4) < 1e-9)
check("Flash の内訳が 704.00 KB -> 上限 563.20 KB",
      abs(b.flash_available_kb - 704.0) < 1e-9 and abs(b.weights_limit_kb - 563.2) < 1e-9)
pooled = b.arena_limit_kb + b.weights_limit_kb          # 729.60 KB（足してはいけない数）
v700 = fits_raw(b, weights_kb=700.0, arena_kb=10.0)
check("2つの池を足した数（729.60 KB）で判定してはいけない",
      abs(pooled - 729.6) < 1e-9 and not v700.ok and v700.ram_ok,
      f"重み 700.00 KB は合計 {pooled:.2f} KB より小さいのに Flash 枠に入らない")

# --- [2] 桁の差 --------------------------------------------------------------
int8_kb = ONNX_INT8_MB * KB
print(f"\n[2] 桁の差（セッション12の int8 モデル {ONNX_INT8_MB} MB＝{int8_kb:,.2f} KB・①実測）")
print(f"重みの上限 {b.weights_limit_kb:.2f} KB に対して {int8_kb / b.weights_limit_kb:.2f} 倍")
print(f"RAM 全体 {b.ram_kb:.0f} KB に対して {int8_kb / b.ram_kb:.1f} 倍")
check("int8 にしても端末E の重み枠の 30 倍以上ある",
      int8_kb / b.weights_limit_kb > 30.0, f"{int8_kb / b.weights_limit_kb:.2f} 倍")
check("int8 モデルは端末E の RAM 全体の 70 倍以上ある",
      int8_kb / b.ram_kb > 70.0, f"{int8_kb / b.ram_kb:.1f} 倍")

# --- [3] 逆算 ----------------------------------------------------------------
limit = b.weights_limit_kb
n_fp32, n_int8 = max_params(limit, 4.0), max_params(limit, 1.0)
bpp_k = bytes_per_param_needed(limit, MODEL_K.params)
bpp_c12 = bytes_per_param_needed(limit, C12_PARAMS)
bpp_05b = bytes_per_param_needed(limit, 500_000_000)
print("\n[3] 逆算（②決定的）")
print(f"重み枠 {limit:.2f} KB に載るパラメータ数: fp32 {n_fp32:,} / int8 {n_int8:,}")
print(f"モデルK（{MODEL_K.params:,}）: {bpp_k:.6f} バイト/パラメータ")
print(f"S12 の分類器（{C12_PARAMS:,}）: {bpp_c12:.6f} バイト（{bpp_c12 * 8:.4f} ビット）")
print(f"0.5B 級（500,000,000）: {bpp_05b:.6f} バイト（{bpp_05b * 8:.4f} ビット）")
check("int8 は fp32 の 4 倍のパラメータを載せられる",
      abs(n_int8 / n_fp32 - 4.0) < 0.001 and n_int8 == 576_716, f"{n_int8:,} 個")
check("モデルK は fp32 のままでも Flash 枠に載る（1パラメータ 4.0 バイト以上使える）",
      bpp_k >= 4.0, f"{bpp_k:.6f} バイト/パラメータ")
check("S12 の分類器は 1bit（0.125 バイト）でも載らない", bpp_c12 < 0.125,
      f"{bpp_c12 * 8:.4f} ビットしか使えない")
check("0.5B 級は 1bit の 100 分の1以下しか使えない", 0.125 / bpp_05b > 100.0,
      f"1bit でも {0.125 / bpp_05b:.1f} 倍足りない")

# --- [4] 中間テンソルの数え方 ------------------------------------------------
w_peak, w_naive = MODEL_W.arena_peak_kb(), MODEL_W.arena_naive_kb()
print("\n[4] 数え方で判定が変わる（モデルW・160x160・int8）")
print(f"ピーク {w_peak:.2f} KB / 素朴に合計 {w_naive:.2f} KB / 上限 {b.arena_limit_kb:.2f} KB")
check("モデルW はピーク 150.00 KB・素朴に合計 206.25 KB",
      abs(w_peak - 150.0) < 0.01 and abs(w_naive - 206.25) < 0.01)
check("上限 166.40 KB はピークと素朴な合計の間にある（数え方で判定が変わる）",
      w_peak <= b.arena_limit_kb < w_naive)
check("入力を下げると RAM が減る（W 150.00 KB -> V 54.00 KB）",
      abs(MODEL_V.arena_peak_kb() - 54.0) < 0.01
      and MODEL_V.arena_peak_kb() < w_peak,
      f"{MODEL_V.arena_peak_kb():.2f} KB")
big = (50_176, 200_704, 100_352, 50_176, 12_544, 2)     # 入力 224x224（練習問題6）
peak_big = max(a + b2 for a, b2 in zip(big, big[1:])) / KB
check("入力 224x224 ではピーク 294.00 KB で上限を超える",
      abs(peak_big - 294.0) < 0.01 and peak_big > b.arena_limit_kb,
      f"上限の {peak_big / b.arena_limit_kb:.1%}")

# --- [5] 重みだけで見積もると外す --------------------------------------------
v32 = fits(b, MODEL_V, bytes_per_param=4.0, act_bytes=4)
v8 = fits(b, MODEL_V)
print("\n[5] 重みだけで見積もると外す（モデルV）")
print(f"fp32: 重み {v32.weights_kb:.2f} KB（Flash {v32.flash_use:.1%}） / "
      f"アリーナ {v32.arena_kb:.2f} KB（RAM {v32.ram_use:.1%}）")
print(f"int8: 重み {v8.weights_kb:.2f} KB（Flash {v8.flash_use:.1%}） / "
      f"アリーナ {v8.arena_kb:.2f} KB（RAM {v8.ram_use:.1%}）")
check("fp32 は Flash には載るのに RAM で落ちる", v32.flash_ok and not v32.ram_ok,
      f"RAM が上限の {v32.ram_use:.1%}")
check("int8 なら両方の池に収まる", v8.ok, v8.text())
check("int8 でも中間テンソルは重みの 1.9 倍以上ある",
      v8.arena_kb / v8.weights_kb > 1.9, f"{v8.arena_kb / v8.weights_kb:.2f} 倍")
c12 = fits(b, MODEL_C12)
check("先に溢れる池はモデルの形で変わる（C12 は RAM に余裕があるのに Flash で落ちる）",
      c12.ram_ok and not c12.flash_ok,
      f"RAM {c12.ram_use:.1%} / Flash {c12.flash_use:.1%}")

# --- [6] 言語モデルは載らない ------------------------------------------------
llm_w_kb = GGUF_Q4_K_M_MB * KB
kv_kb = KV_PER_TOKEN_KB_05B * SEQ_LEN
print(f"\n[6] 0.5B の言語モデル（重み {GGUF_Q4_K_M_MB} MB・①実測／KVキャッシュは S03 の式）")
print(f"重み {llm_w_kb:,.2f} KB は枠 {limit:.2f} KB の {llm_w_kb / limit:.1f} 倍")
print(f"KVキャッシュ（系列長 {SEQ_LEN:,}）{kv_kb:,.2f} KB は枠 "
      f"{b.arena_limit_kb:.2f} KB の {kv_kb / b.arena_limit_kb:.1f} 倍")
check("重みは端末E の枠の 600 倍以上", llm_w_kb / limit > 600.0,
      f"{llm_w_kb / limit:.1f} 倍")
check("KVキャッシュだけでも枠の 100 倍以上", kv_kb / b.arena_limit_kb > 100.0,
      f"{kv_kb / b.arena_limit_kb:.1f} 倍")
check("アリーナ上限に入るのは 0.5B 級で 13 トークン・8B 級で 1 トークン",
      (kv_tokens(b.arena_limit_kb, KV_PER_TOKEN_KB_05B),
       kv_tokens(b.arena_limit_kb, KV_PER_TOKEN_KB_8B)) == (13, 1),
      "セッション3の 12.00 KB / 128.00 KB から")

# --- [7] C の配列 ------------------------------------------------------------
q, scale = quantize_symmetric(DEMO_FP32)
src = emit_c_array("model_w1", q, scale)
fb, sb = flash_bytes(q), source_bytes(src)
low, high = source_bounds(int(q.size))
print("\n[7] C の配列に落とす（②決定的）")
print(f"量子化後: {q.tolist()} / スケール {scale:.8f}")
print(f"Flash {fb} バイト / ソース {sb} バイト（{sb / fb:.1f} 倍）")
check("8 要素の量子化結果が決定的に決まる",
      q.tolist() == [32, -79, 127, -16, 48, -111, 70, 98], f"{q.tolist()}")
check("スケールは 最大の絶対値 ÷ 127", abs(scale * 127 - 0.4) < 1e-6, f"{scale:.8f}")
check("Flash に焼かれるのは要素数ぶんだけ（8 バイト）", fb == 8)
check("ソースのバイト数は下限と上限の式に収まる", low < sb < high,
      f"{low} < {sb} < {high}")

n_big = 1024
data_big = demo_int8(n_big)
src_big = emit_c_array("model_big", data_big, 1.0 / 127.0)
fb_big, sb_big = flash_bytes(data_big), source_bytes(src_big)
low_big, high_big = source_bounds(n_big)
print(f"要素数 {n_big:,}: Flash {fb_big:,} バイト / ソース {sb_big:,} バイト "
      f"（{sb_big / fb_big:.1f} 倍）")
check(f"要素数 {n_big:,} でも Flash は要素数ぶんだけ", fb_big == n_big)
check("ソースのバイト数は下限と上限の式に収まる（要素数 1,024）",
      low_big < sb_big < high_big, f"{low_big:,} < {sb_big:,} < {high_big:,}")
check("要素数が増えるとソース ÷ Flash の比は小さくなる（ヘッダの寄与が薄まる）",
      sb_big / fb_big < sb / fb, f"{sb / fb:.1f} 倍 -> {sb_big / fb_big:.1f} 倍")

const_copy = ram_copy_kb(MODEL_K.params, True)
no_const_copy = ram_copy_kb(MODEL_K.params, False)
arena_k = MODEL_K.arena_peak_kb()
print(f"モデルK: const あり RAM {arena_k:.2f} KB（{arena_k / b.arena_limit_kb:.1%}） / "
      f"const なし RAM {arena_k + no_const_copy:.2f} KB "
      f"（{(arena_k + no_const_copy) / b.arena_limit_kb:.1%}）")
check("const を付ければ重みのコピーは RAM に載らない", const_copy == 0.0)
check("const を忘れるとモデルK の RAM 使用率が 3 倍以上になる",
      (arena_k + no_const_copy) / arena_k > 3.0,
      f"{arena_k / b.arena_limit_kb:.1%} -> {(arena_k + no_const_copy) / b.arena_limit_kb:.1%}")
check("C12 を const なしで置くとアリーナ上限の 100 倍を超える",
      MODEL_C12.weights_kb() / b.arena_limit_kb > 100.0,
      f"{MODEL_C12.weights_kb() / b.arena_limit_kb:.1f} 倍")

# --- [8] 対応演算子 ----------------------------------------------------------
r_k = check_ops("K", GRAPHS["K キーワード検出"])
r_c12 = check_ops("C12", GRAPHS["C12 セッション12の分類器"])
r_llm = check_ops("LLM", GRAPHS["小さな言語モデル"])
print(f"\n[8] 対応演算子（③前提値の対応表 {len(SUPPORTED)} 個）")
print(f"K: 未対応 {r_k.unsupported or 'なし'}")
print(f"C12: 未対応 {r_c12.unsupported}")
print(f"言語モデル: 未対応 {r_llm.unsupported}")
check("モデルK は対応表の演算子だけで作られている", r_k.ok)
check("C12 で未対応なのは MatMul だけ（置き換えれば済む）",
      r_c12.unsupported == ("MatMul",))
check("言語モデルは 5 個未対応で、Attention は置き換えられない",
      r_llm.unsupported == ("Attention", "Embedding", "Gelu", "LayerNormalization",
                            "MatMul") and "タスクを変える" in advice("Attention"))
check("メモリが通っても演算子で落ちることがある（関門は2つ）",
      fits(b, MODEL_K).ok and not check_ops(
          "K", GRAPHS["K キーワード検出"], SUPPORTED - {"Softmax"}).ok,
      "Softmax を持たないランタイムではモデルK も止まる")

# --- [9] タスク × 端末クラス -------------------------------------------------
print("\n[9] タスク × 端末クラス（③前提値の設計）")
for t in TASKS:
    print(f"{t.name}: 端末E {'載る' if mcu_ok(t) else '載らない'} / "
          f"端末D {'載る' if mb_ok(DEVICE_D, t) else '載らない'} / "
          f"端末A {'載る' if mb_ok(DEVICE_A, t) else '載らない'}")
check("端末D・端末A の上限は S11 と同じ（512.00 MB / 1,228.80 MB）",
      abs(DEVICE_D.limit_mb - 512.0) < 1e-9 and abs(DEVICE_A.limit_mb - 1228.8) < 1e-9)
check("マイコン級に載るのは前半の3件だけ",
      [mcu_ok(t) for t in TASKS] == [True, True, True, False, False, False])
check("端末クラスを1つ上げると載るタスクが1段増える（S12 の分類器は端末D で載る）",
      not mcu_ok(TASKS[3]) and mb_ok(DEVICE_D, TASKS[3]),
      f"端末D では {TASKS[3].total_mb():.2f} MB")
check("0.5B の言語モデルは端末D では載らず端末A で載る",
      not mb_ok(DEVICE_D, TASKS[4]) and mb_ok(DEVICE_A, TASKS[4]),
      f"合計 {TASKS[4].total_mb():.2f} MB / 端末D の上限 {DEVICE_D.limit_mb:.2f} MB")
check("8B 級はどの端末クラスでも載らない",
      not any([mcu_ok(TASKS[5]), mb_ok(DEVICE_D, TASKS[5]), mb_ok(DEVICE_A, TASKS[5])]),
      f"合計 {TASKS[5].total_mb():,.2f} MB")

# --- [10] 送る量の比（練習問題10）--------------------------------------------
gb_result = monthly_upload_gb(16, per_hour=60, devices=500)
gb_audio = monthly_upload_gb(16_000 * 2, per_hour=60, devices=500)
print("\n[10] 送る量（③前提値：毎分1回・24時間・30日・500 台）")
print(f"結果だけ送る（16 バイト）: {gb_result:.2f} GB/月")
print(f"音声を送る（32,000 バイト）: {gb_audio:.2f} GB/月")
check("結果だけ送れば通信量は 2,000 分の1になる",
      abs(gb_audio / gb_result - 2000.0) < 1e-6,
      f"{gb_result:.2f} GB -> {gb_audio:.2f} GB")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print(f"\nセッション14の検証はすべて成功しました（{checked} 件）。")
