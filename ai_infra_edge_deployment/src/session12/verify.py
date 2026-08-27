#!/usr/bin/env python3
"""セッション12の自己検証：ONNX への変換と int8 量子化。

  python src/session12/verify.py

**レイテンシの絶対値は検証しない**（実行ごとに揺れるため）。検証するのは3種類。

  ① 決定的なもの         : 形状・opset・ノード数・重みの要素数・サイズ比
  ② 向きが安定した関係   : int8 は小さい／規模が大きいほど遅い／判断は変わらない
  ③ 落ちる・落ちないの区別: 形状・名前・型を間違えたら実行時に落ちること

サーバもネットワークも要らないので数十秒で終わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from equivalence import compare  # noqa: E402
from failure_lab import run_cases  # noqa: E402
from infrakit.edge import file_size_mb, make_session  # noqa: E402
from inspect_onnx import op_counts, quant_nodes, shape_text  # noqa: E402
from quant_report import ONNX_DIR, ensure_fp32, fixed_input, quantize  # noqa: E402
from scale_check import ensure_model, measure, params  # noqa: E402

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


print("=== セッション12：モデルをデバイスに載せる ===")

fp32 = ensure_fp32()
int8 = ONNX_DIR / "classifier_int8.onnx"
quant_seconds = quantize(fp32, int8)
print(f"量子化に {quant_seconds:.1f} 秒（1回だけ。端末では行わない）")

m32 = onnx.load(str(fp32))
m8 = onnx.load(str(int8))

# --- [1] 変換の結果（決定的）------------------------------------------------
print("\n[1] 変換されたグラフ（誰の環境でも同じ値になる）")
elems = sum(int(numpy_helper.to_array(i).size) for i in m32.graph.initializer)
print(f"入力 {shape_text(m32.graph.input[0])} -> 出力 {shape_text(m32.graph.output[0])} / "
      f"opset {m32.opset_import[0].version} / ノード {len(m32.graph.node)} / "
      f"重みの要素数 {elems:,}")
check("入力の形状が [1, 384] に固定されている",
      shape_text(m32.graph.input[0]) == "[1, 384]", shape_text(m32.graph.input[0]))
check("出力の形状が [1, 6] に固定されている",
      shape_text(m32.graph.output[0]) == "[1, 6]", shape_text(m32.graph.output[0]))
check("opset が 20", m32.opset_import[0].version == 20)
check("ノードが 9 個（MatMul 3 / Add 3 / Relu 2 / Softmax 1）",
      len(m32.graph.node) == 9
      and op_counts(m32) == {"Add": 3, "MatMul": 3, "Relu": 2, "Softmax": 1},
      ", ".join(f"{k} x{v}" for k, v in op_counts(m32).items()))
check("重みの要素数が 18,382,854（行列 18.37M ＋ バイアス）", elems == 18_382_854,
      f"fp32 なので × 4 バイト = {elems * 4 / 1024 ** 2:.2f} MB")
check("fp32 のグラフには量子化のノードが無い", quant_nodes(m32) == 0)

# --- [2] 量子化はサイズを減らし、ノードを増やす ------------------------------
size32, size8 = file_size_mb(fp32), file_size_mb(int8)
print("\n[2] 量子化の効果（サイズは減り、グラフは増える）")
check("int8 のサイズが fp32 の半分未満", size8 < size32 * 0.5,
      f"{size32:.2f} MB -> {size8:.2f} MB（{size8 / size32:.1%}）")
check("量子化するとノードが増える（量子化と逆量子化が挟まる）",
      len(m8.graph.node) > len(m32.graph.node),
      f"{len(m32.graph.node)} -> {len(m8.graph.node)} ノード")
check("int8 のグラフに量子化のノードが入っている", quant_nodes(m8) > 0,
      f"{quant_nodes(m8)} 個")

# --- [3] 出力（精度は2つの指標で見る）---------------------------------------
feeds = fixed_input()
ref = make_session(fp32, 1).run(None, feeds)[0]
got = make_session(int8, 1).run(None, feeds)[0]
diff = float(np.abs(ref - got).max())
print("\n[3] 出力の比較（1件・固定入力）")
check("確率の合計が 1 になる（fp32）", abs(float(ref.sum()) - 1.0) < 1e-4,
      f"{float(ref.sum()):.6f}")
check("量子化しても最大クラスが変わらない",
      int(np.argmax(ref)) == int(np.argmax(got)),
      f"fp32={int(np.argmax(ref))} int8={int(np.argmax(got))}")
check("出力は完全一致ではない（だから最大クラスだけ見てはいけない）", diff > 0.0,
      f"確率の最大差 {diff:.6f}")
check("確率の最大差が 0.05 未満", diff < 0.05, f"{diff:.6f}")

# --- [4] 等価性の検証（複数サンプル）----------------------------------------
# 上限は equivalence.py の既定（0.01）より緩い 0.02 にしている。CPU の種類で
# 演算の丸めが変わるため、**検証には余裕を持たせる**のが原則（絶対値を約束しない）。
eq = compare(samples=64, margin=0.05, max_diff_limit=0.02, fp32=fp32, int8=int8)
print("\n[4] 等価性の検証（64 件）")
print(f"   {eq.summary()} / マージン 0.05 以上 {eq.clear_agree}/{eq.clear_total} 件一致 / "
      f"0.05 未満 {eq.close_agree}/{eq.close_total} 件一致")
check("確率の最大差が許容内（64 件すべて）", eq.max_diff <= eq.max_diff_limit,
      f"最大 {eq.max_diff:.6f} <= {eq.max_diff_limit}")
check("マージンのあるサンプルは最大クラスが変わらない",
      eq.clear_agree == eq.clear_total,
      f"{eq.clear_agree}/{eq.clear_total} 件（際どいサンプルの入れ替わりは不合格にしない）")
check("等価性の判定が合格になる", eq.passed)

# --- [5] 失敗の切り分け（落ちる・落ちないの区別）-----------------------------
print("\n[5] 失敗の切り分け")
for i, case in enumerate(run_cases(), start=1):
    check(f"[{i}] {case.label} は{'落ちる' if case.expect_fail else '通る'}",
          case.as_expected, f"{case.where} / {case.result_text}")

# --- [6] 測れる規模か（規模とレイテンシの向き）-------------------------------
small = ensure_model(512)
p50_small, _ = measure(small, threads=1, repeats=20)
p50_large, _ = measure(fp32, threads=1, repeats=20)
print("\n[6] 測れる規模か")
print(f"   隠れ層 512（{params(512) / 1e6:.2f}M・{file_size_mb(small):.2f} MB）: "
      f"定常 p50 {p50_small:.2f} ms")
print(f"   隠れ層 4096（{params(4096) / 1e6:.2f}M・{size32:.2f} MB）: "
      f"定常 p50 {p50_large:.2f} ms")
check("隠れ層が大きいほど遅い（規模とレイテンシは同じ向き）", p50_small < p50_large,
      f"{p50_small:.2f} ms < {p50_large:.2f} ms。"
      "小さすぎる規模で『N 倍速い』を語らないこと")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print(f"\nセッション12の検証はすべて成功しました（{checked} 件）。")
