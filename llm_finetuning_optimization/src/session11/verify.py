#!/usr/bin/env python3
"""セッション11の自己検証：動的量子化と静的量子化・キャリブレーション・出力差。

検証する主張（本文に書いた内容と1対1で対応させる）:

  1. 量子化の対象は「重み」と「活性化」の2つある。重みだけ int8 にする場合より、
     活性化も int8 にする場合の方が誤差が大きい
  2. 活性化のスケールを入力ごとに決める（動的量子化）方が、事前に固定する
     （静的量子化）より誤差が小さい
  3. キャリブレーションデータが偏ると、活性化のスケールを読み違えて誤差が跳ね上がる
     - 小さい入力だけで測る → 範囲が狭すぎてクリップする
     - 桁違いの外れ値を含める → 範囲が広すぎて目盛りが粗くなる（クリップはしない）
     - パーセンタイルでスケールを決めると外れ値の影響を抑えられる
  4. 自作の小さな分類器（2.71M パラメータ）を ONNX に書き出して動的量子化すると、
     サイズが fp32 の半分未満になり、予測はほとんど変わらない
  5. 偏ったキャリブレーションで静的量子化すると、代表データより出力差が大きくなる

1〜3 は NumPy だけの検算なので一瞬で終わる。4〜5 は数MBの自作モデルを使うので
既定環境（メモリ 5.8GB）でも数十秒で完走する。**LLM（135M・0.5B）は読み込まない**
（optimum 経由の ONNX 書き出しは 135M でも既定環境では OOM で失敗する）。

  python src/session11/verify.py
  SKIP_ONNX=1 python src/session11/verify.py   # 4〜5 を飛ばす（NumPy の検算だけ）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SEED = 20260815
failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def scale_from(x, bits: int = 8) -> float:
    """対称量子化のスケール（S10 と同じ式）。max|x| をフルスケールに合わせる。"""
    qmax = 2 ** (bits - 1) - 1
    return float(np.abs(np.asarray(x)).max()) / qmax


def quantize_with_scale(x, scale: float, bits: int = 8):
    """**スケールを外から与える**のがこの章の要点。誰がどうやって決めるかが動的/静的の差。"""
    qmax = 2 ** (bits - 1) - 1
    q = np.clip(np.rint(np.asarray(x, dtype=np.float64) / scale), -qmax - 1, qmax)
    return q * scale


def clip_ratio(x, scale: float, bits: int = 8) -> float:
    """与えたスケールで表せる範囲を超える要素の割合（＝つぶれる要素の割合）。"""
    qmax = 2 ** (bits - 1) - 1
    return float(np.mean(np.abs(np.asarray(x)) > scale * qmax))


def rmse(a, b) -> float:
    return float(np.sqrt(np.mean((np.asarray(a, dtype=np.float64) - np.asarray(b)) ** 2)))


def mixture(rng, shape):
    """活性化らしい分布：大半は普通の大きさで、5% だけ3倍散らばる（外れ値がある）。"""
    base = rng.normal(0.0, 1.0, shape)
    wide = rng.normal(0.0, 3.0, shape)
    pick = rng.random(shape) < 0.05
    return np.where(pick, wide, base)


# --- 1. 重みだけ量子化する場合と、活性化も量子化する場合 ---------------------
print("=== 1. 重みだけ量子化する場合と、活性化も量子化する場合 ===")
rng = np.random.default_rng(SEED)
W = rng.normal(0.0, 0.05, (64, 64))     # 重み：作った時点で決まっている（事前に量子化できる）
X = mixture(rng, (32, 64))              # 活性化：入力ごとに変わる（事前には分からない）
y_ref = X @ W

scale_w = scale_from(W)
W_q = quantize_with_scale(W, scale_w)
err_weight_only = rmse(y_ref, X @ W_q)

X_dynamic = np.vstack([quantize_with_scale(row, scale_from(row)) for row in X])
err_dynamic = rmse(y_ref, X_dynamic @ W_q)

calib_repr = mixture(rng, (2048, 64))               # 代表的なキャリブレーションデータ
calib_narrow = rng.normal(0.0, 0.3, (2048, 64))     # 小さい入力だけに偏ったデータ
scale_repr, scale_narrow = scale_from(calib_repr), scale_from(calib_narrow)
err_static_repr = rmse(y_ref, quantize_with_scale(X, scale_repr) @ W_q)
err_static_narrow = rmse(y_ref, quantize_with_scale(X, scale_narrow) @ W_q)

print(f"  重みのスケール={scale_w:.3e} / 活性化のスケール: "
      f"静的・代表={scale_repr:.3e} 静的・偏り={scale_narrow:.3e}")
print(f"  {'方式':<34}{'RMSE':>12}{'活性化のクリップ率':>20}")
print(f"  {'重みだけ int8（活性化 fp32）':<34}{err_weight_only:>12.3e}{'—':>20}")
print(f"  {'活性化も int8・動的':<34}{err_dynamic:>12.3e}{'0.0%':>20}")
print(f"  {'活性化も int8・静的（代表）':<34}{err_static_repr:>12.3e}"
      f"{clip_ratio(X, scale_repr) * 100:>19.1f}%")
print(f"  {'活性化も int8・静的（偏り）':<34}{err_static_narrow:>12.3e}"
      f"{clip_ratio(X, scale_narrow) * 100:>19.1f}%")

check("重みだけ int8 にするより、活性化も int8 にする方が誤差が大きい",
      err_dynamic > err_weight_only * 1.3,
      f"{err_weight_only:.3e} -> {err_dynamic:.3e}（{err_dynamic / err_weight_only:.2f} 倍）")
check("動的量子化（入力ごとにスケールを決める）は静的量子化（事前に固定）より誤差が小さい",
      err_dynamic < err_static_repr,
      f"動的 {err_dynamic:.3e} < 静的・代表 {err_static_repr:.3e}")
check("偏ったキャリブレーションの静的量子化は代表データの3倍以上の誤差になる",
      err_static_narrow > err_static_repr * 3,
      f"{err_static_repr:.3e} -> {err_static_narrow:.3e}"
      f"（{err_static_narrow / err_static_repr:.1f} 倍）")
check("偏ったキャリブレーションでは活性化のクリップが 5% 以上の要素で起きる",
      clip_ratio(X, scale_narrow) > 0.05,
      f"クリップ率 {clip_ratio(X, scale_narrow) * 100:.1f}%（代表データなら "
      f"{clip_ratio(X, scale_repr) * 100:.1f}%）")

# --- 2. キャリブレーションデータの偏り方は2方向ある -------------------------
print("\n=== 2. キャリブレーションデータの偏り方は2方向ある ===")
real = mixture(rng, (512, 256))                      # 本番で流れてくる活性化
cal_repr = mixture(rng, (64, 256))                   # A：代表的
cal_short = rng.normal(0.0, 0.35, (64, 256))         # B：小さい入力だけ（範囲が狭すぎる）
cal_outlier = mixture(rng, (64, 256))
cal_outlier[0, 0] = 120.0                            # C：桁違いの1件が混ざった（範囲が広すぎる）

rows = []
for label, cal in (("A 代表的", cal_repr), ("B 小さい入力だけ", cal_short),
                   ("C 外れ値が1件混ざる", cal_outlier)):
    s = scale_from(cal)
    rows.append((label, s, rmse(real, quantize_with_scale(real, s)), clip_ratio(real, s)))
scale_pct = float(np.percentile(np.abs(cal_outlier), 99.9)) / 127
rows.append(("C を 99.9 パーセンタイルで", scale_pct,
             rmse(real, quantize_with_scale(real, scale_pct)), clip_ratio(real, scale_pct)))

print(f"  {'キャリブレーションデータ':<30}{'スケール':>12}{'RMSE':>12}{'クリップ率':>14}")
for label, s, err, clip in rows:
    print(f"  {label:<30}{s:>12.3e}{err:>12.3e}{clip * 100:>13.2f}%")

err_a, err_b, err_c, err_pct = (r[2] for r in rows)
check("小さい入力だけでキャリブレーションすると誤差が代表データの3倍以上になる",
      err_b > err_a * 3, f"{err_a:.3e} -> {err_b:.3e}（{err_b / err_a:.1f} 倍）")
check("外れ値を含めすぎたキャリブレーションはクリップしないのに誤差が3倍以上になる",
      err_c > err_a * 3 and rows[2][3] < 1e-4,
      f"{err_a:.3e} -> {err_c:.3e}（クリップ率 {rows[2][3] * 100:.2f}%）")
check("99.9 パーセンタイルでスケールを決めると外れ値の影響が半分以下になる",
      err_pct < err_c / 2, f"{err_c:.3e} -> {err_pct:.3e}")

if os.environ.get("SKIP_ONNX") == "1":
    print("\nSKIP_ONNX=1 のため 3〜4 を飛ばします（ONNX を作りません）。")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print("\nセッション11の検証（NumPy の検算のみ）はすべて成功しました。")
    sys.exit(0)

# --- 3. 自作モデルを ONNX に書き出して動的量子化する -----------------------
print("\n=== 3. 自作モデルを ONNX に書き出して動的量子化する ===")
from ftkit.quantize import quantize_onnx_dynamic  # noqa: E402

from tinyclf import (  # noqa: E402
    int8_initializer_count,
    export_fp32,
    latency_ms,
    make_features,
    model_path,
    op_histogram,
    output_diff,
    param_count,
    predict,
    quantize_static_int8,
)

eval_X = make_features(SEED, 96, 8, 96)              # 本番相当：短い問い合わせも長いものもある
calib_repr_X = make_features(SEED + 1, 64, 8, 96)    # 代表的なキャリブレーションデータ
calib_short_X = make_features(SEED + 2, 64, 8, 12)   # 短い問い合わせだけに偏ったデータ
for label, data in (("評価データ", eval_X), ("キャリブA（代表）", calib_repr_X),
                    ("キャリブB（短いものだけ）", calib_short_X)):
    total = data.sum(axis=1)
    print(f"  {label:<26} n={len(data):>3}  文字数 {int(total.min()):>3}〜{int(total.max()):>3}")

fp32_dir, fp32_result = export_fp32("session11-fp32")
expected_mib = param_count() * 4 / 1024 / 1024
hist = op_histogram(model_path(fp32_dir))
print(f"  パラメータ数 {param_count():,} → fp32 の計算値 {expected_mib:.2f} MiB")
print(f"  書き出し {fp32_result.seconds:.1f}s / 実サイズ {fp32_result.size_mb:.2f} MiB")
print(f"  オペレータ: {hist}")
check("書き出した ONNX に MatMul がある（量子化の対象になる演算）",
      hist.get("MatMul", 0) >= 1,
      f"MatMul={hist.get('MatMul', 0)}（0 なら Gemm に変換されている。"
      f"tinyclf.build_model の行列積の書き方を確認する）")
check("fp32 の ONNX のサイズが計算値（パラメータ数 × 4 バイト）と ±20% 以内で一致する",
      0.9 * expected_mib < fp32_result.size_mb < 1.2 * expected_mib,
      f"計算 {expected_mib:.2f} MiB / 実測 {fp32_result.size_mb:.2f} MiB")

dyn_result = quantize_onnx_dynamic(fp32_dir, "session11-int8-dynamic")
dyn_dir = fp32_dir.parent / "session11-int8-dynamic"
dyn_ratio = dyn_result.size_mb / fp32_result.size_mb
print(f"  動的量子化 {dyn_result.seconds:.1f}s / {dyn_result.size_mb:.2f} MiB "
      f"（fp32 比 {dyn_ratio * 100:.1f}%）")
print(f"  オペレータ: {op_histogram(model_path(dyn_dir))}")
check("動的量子化で ONNX のサイズが fp32 の 45% 未満になる",
      dyn_ratio < 0.45, f"{fp32_result.size_mb:.2f} MiB -> {dyn_result.size_mb:.2f} MiB")
check("動的量子化した ONNX の重みが int8 で保存されている",
      int8_initializer_count(model_path(dyn_dir)) >= 1,
      f"int8 の重み {int8_initializer_count(model_path(dyn_dir))} 本")

p_fp32 = predict(fp32_dir, eval_X)
p_dyn = predict(dyn_dir, eval_X)
d_dyn = output_diff(p_fp32, p_dyn)
print(f"  出力差（動的）: 確率の最大差={d_dyn['max_abs']:.6f} "
      f"平均差={d_dyn['mean_abs']:.6f} 予測一致率={d_dyn['argmax_agree']:.3f}")
check("fp32 の出力が確率になっている（各行の合計が 1）",
      bool(np.allclose(p_fp32.sum(axis=1), 1.0, atol=1e-5)),
      f"合計の範囲 {p_fp32.sum(axis=1).min():.6f}〜{p_fp32.sum(axis=1).max():.6f}")
check("動的量子化の前後で予測ラベルの一致率が 0.90 以上",
      d_dyn["argmax_agree"] >= 0.90, f"{d_dyn['argmax_agree']:.3f}")
check("動的量子化の前後で確率の最大差が 0.05 未満",
      d_dyn["max_abs"] < 0.05, f"{d_dyn['max_abs']:.6f}")

# --- 4. 静的量子化とキャリブレーションの偏り（実物の ONNX で） --------------
print("\n=== 4. 静的量子化とキャリブレーションの偏り（実物の ONNX で） ===")
static_good = quantize_static_int8(fp32_dir, "session11-int8-static-good", calib_repr_X)
static_bad = quantize_static_int8(fp32_dir, "session11-int8-static-biased", calib_short_X)
good_dir = fp32_dir.parent / "session11-int8-static-good"
bad_dir = fp32_dir.parent / "session11-int8-static-biased"
p_good, p_bad = predict(good_dir, eval_X), predict(bad_dir, eval_X)
d_good, d_bad = output_diff(p_fp32, p_good), output_diff(p_fp32, p_bad)
print(f"  静的（代表）{static_good.seconds:.1f}s / {static_good.size_mb:.2f} MiB")
print(f"  静的（偏り）{static_bad.seconds:.1f}s / {static_bad.size_mb:.2f} MiB")

one = eval_X[0]
table = [
    ("fp32（基準）", fp32_result.size_mb, latency_ms(fp32_dir, one), None),
    ("int8 動的", dyn_result.size_mb, latency_ms(dyn_dir, one), d_dyn),
    ("int8 静的・代表データ", static_good.size_mb, latency_ms(good_dir, one), d_good),
    ("int8 静的・偏ったデータ", static_bad.size_mb, latency_ms(bad_dir, one), d_bad),
]
print(f"\n  {'形式':<24}{'サイズ(MiB)':>13}{'fp32比':>9}{'レイテンシ(ms)':>16}"
      f"{'確率の最大差':>14}{'一致率':>9}")
for label, size, ms, diff in table:
    ratio = f"{size / fp32_result.size_mb * 100:.1f}%"
    if diff is None:
        print(f"  {label:<24}{size:>13.2f}{ratio:>9}{ms:>16.4f}{'—':>14}{'—':>9}")
    else:
        print(f"  {label:<24}{size:>13.2f}{ratio:>9}{ms:>16.4f}"
              f"{diff['max_abs']:>14.6f}{diff['argmax_agree']:>9.3f}")
print("  ※ レイテンシは環境ごとに変わります。比較は同じ環境の中だけで行ってください。")

check("静的量子化（代表データ）でもサイズが fp32 の 45% 未満になる",
      static_good.size_mb / fp32_result.size_mb < 0.45,
      f"{static_good.size_mb:.2f} MiB / {fp32_result.size_mb:.2f} MiB")
check("静的量子化（代表データ）の予測ラベル一致率が 0.80 以上",
      d_good["argmax_agree"] >= 0.80, f"{d_good['argmax_agree']:.3f}")
check("偏ったキャリブレーションの静的量子化は確率の最大差が代表データの 1.5 倍以上になる",
      d_bad["max_abs"] > d_good["max_abs"] * 1.5,
      f"{d_good['max_abs']:.6f} -> {d_bad['max_abs']:.6f}"
      f"（{d_bad['max_abs'] / max(d_good['max_abs'], 1e-12):.1f} 倍）")
check("偏ったキャリブレーションの静的量子化は予測ラベル一致率が代表データ以下になる",
      d_bad["argmax_agree"] <= d_good["argmax_agree"],
      f"代表 {d_good['argmax_agree']:.3f} / 偏り {d_bad['argmax_agree']:.3f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション11の検証はすべて成功しました。")
