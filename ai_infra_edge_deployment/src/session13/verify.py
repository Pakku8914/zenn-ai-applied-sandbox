#!/usr/bin/env python3
"""セッション12・13の自己検証：エッジ側の量子化と実行。

サーバを使わないので数秒で終わる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.edge import bench_session, file_size_mb, first_inference_ms, make_session  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
ONNX_DIR = SANDBOX / "models" / "onnx"
SEED = 20260815
INPUT_DIM = 384

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


fp32 = ONNX_DIR / "classifier_fp32.onnx"
if not fp32.exists():
    print("モデルが無いので作成します（tools/make_edge_model.py）")
    sys.path.insert(0, str(SANDBOX / "tools"))
    from tools.make_edge_model import build

    build(4096, "classifier_fp32")

int8 = ONNX_DIR / "classifier_int8.onnx"
from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: E402

quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)

# --- サイズ -----------------------------------------------------------------
size_fp32, size_int8 = file_size_mb(fp32), file_size_mb(int8)
check("fp32 モデルが作られている", size_fp32 > 5, f"{size_fp32:.2f} MB")
check("int8 でサイズが半分以下になる", size_int8 < size_fp32 * 0.5,
      f"{size_fp32:.2f} MB -> {size_int8:.2f} MB（{size_int8 / size_fp32 * 100:.1f}%）")

# --- 出力の一致 -------------------------------------------------------------
rng = np.random.default_rng(SEED)
x = rng.normal(size=(1, INPUT_DIM)).astype(np.float32)
feeds = {"input": x}
ref = make_session(fp32, 1).run(None, feeds)[0]
got = make_session(int8, 1).run(None, feeds)[0]
diff = float(np.abs(ref - got).max())
check("確率の合計が 1 になる（fp32）", abs(float(ref.sum()) - 1.0) < 1e-4, f"{float(ref.sum()):.6f}")
check("量子化しても最大クラスが変わらない",
      int(np.argmax(ref)) == int(np.argmax(got)),
      f"fp32={int(np.argmax(ref))} int8={int(np.argmax(got))}")
check("出力差が小さい", diff < 0.01, f"最大差 {diff:.6f}")

# --- 初回推論と定常時（ウォームアップの必要性）------------------------------
# タイミングは環境と負荷で揺れるので「初回が遅い」ことは断定しない（報告に留める）。
# 断定するのは方向が安定している性質だけにする。
for label, path in (("fp32", fp32), ("int8", int8)):
    first = first_inference_ms(path, feeds, threads=1)
    steady = bench_session(make_session(path, 1), feeds, label, path, 1, repeats=30)
    ratio = first / max(steady.latency_ms["p50"], 1e-9)
    print(f"   {label}: 初回 {first:.2f}ms / 定常 p50 {steady.latency_ms['p50']:.2f}ms "
          f"（{ratio:.1f} 倍）")
    check(f"{label}: 定常時のレイテンシが測定可能な大きさ（0.1ms 以上）",
          steady.latency_ms["p50"] >= 0.1,
          f"{steady.latency_ms['p50']:.2f}ms"
          "（これより小さいと測定ノイズに埋もれるのでモデルを大きくする）")

# --- int8 の方が速い --------------------------------------------------------
b32 = bench_session(make_session(fp32, 1), feeds, "fp32", fp32, 1, repeats=50)
b8 = bench_session(make_session(int8, 1), feeds, "int8", int8, 1, repeats=50)
check("int8 の方が速い", b8.latency_ms["p50"] < b32.latency_ms["p50"],
      f"{b32.latency_ms['p50']:.2f}ms -> {b8.latency_ms['p50']:.2f}ms")

# --- スレッド数の効き方（断定せず観測する）----------------------------------
# スレッドを増やせば速くなるとは限らない。モデルの大きさと CPU 数で変わるため、
# ここでは「測って選ぶ」ことだけを確認する（セッション13の演習の入口）。
t1 = bench_session(make_session(int8, 1), feeds, "int8", int8, 1, repeats=50)
t2 = bench_session(make_session(int8, 2), feeds, "int8", int8, 2, repeats=50)
t4 = bench_session(make_session(int8, 4), feeds, "int8", int8, 4, repeats=50)
print(f"   int8: スレッド1 {t1.latency_ms['p50']:.2f}ms / "
      f"スレッド2 {t2.latency_ms['p50']:.2f}ms / スレッド4 {t4.latency_ms['p50']:.2f}ms")
best = min((t1, t2, t4), key=lambda b: b.latency_ms["p50"])
print(f"   最速はスレッド {best.threads}（{best.latency_ms['p50']:.2f}ms）")
check("スレッド数を振って比較できる",
      all(b.latency_ms["p50"] > 0 for b in (t1, t2, t4)),
      "どのスレッド数が速いかは環境依存なので、必ず自分の環境で測る")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション12・13の検証はすべて成功しました。")
