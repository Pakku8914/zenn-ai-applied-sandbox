#!/usr/bin/env python3
"""セッション10の自己検証：量子化の式・ブロック単位の量子化・GGUF のサイズ・統合済みモデル。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 対称量子化の誤差は scale/2 以下に収まる（scale = max|x| / qmax）
  2. 8 ビットから 4 ビットに落とすと scale が 127/7 倍になり、誤差もその分増える
  3. 値が正の狭い範囲に偏っているときは、ゼロ点つき（非対称）の方が誤差が小さい
  4. 手計算例（範囲 -1.0〜3.0 を int8 非対称）の scale と zero_point が実装と一致する
  5. 外れ値が1つ混ざると「テンソル全体で1つのスケール」方式は誤差が跳ね上がる。
     32 要素のブロックごとにスケールを持つと影響が局所化する（K 系の発想）
  6. ブロックごとに fp16 スケールを1つ持つ追加コストは 0.5 ビット/重み（Q8_0 の 8.5 ビット）
  7. gguf/*.gguf があればサイズと f16 比の表を出す（無ければスキップする）
  8. save_merged で統合済みモデル（HF形式）が書き出せる ＝ GGUF 変換の入力が作れる

1〜7 はモデルを読まないので数秒で終わる。8 は SmolLM2-135M を1体だけ読み、学習はせず
（LoRA を付けて即統合）、del と gc.collect() で解放する。既定環境はメモリ 5.8GB なので、
**GGUF への変換（別コンテナ）とこのスクリプトを同時に走らせない。**

  python src/session10/verify.py
  SKIP_MERGE=1 python src/session10/verify.py   # 8 を飛ばす（モデルを一切読まない）
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.quantize import dir_size_mb  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
GGUF_DIR = SANDBOX / "gguf"
SEED = 20260815
BLOCK = 32

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def quantize_symmetric(x, bits: int):
    """対称量子化。ゼロ点を持たず scale だけで表す（Q8_0 の発想）。"""
    qmax = 2 ** (bits - 1) - 1
    scale = float(np.abs(x).max()) / qmax
    q = np.clip(np.rint(np.asarray(x, dtype=np.float64) / scale), -qmax - 1, qmax)
    return q, scale, q * scale


def quantize_affine(x, bits: int):
    """非対称量子化。scale と zero_point の2つで表す（値が偏っているときに効く）。"""
    qmin, qmax = 0, 2 ** bits - 1
    lo, hi = float(np.min(x)), float(np.max(x))
    scale = (hi - lo) / (qmax - qmin)
    zero_point = int(np.rint(qmin - lo / scale))
    q = np.clip(np.rint(np.asarray(x, dtype=np.float64) / scale) + zero_point, qmin, qmax)
    return q, scale, zero_point, (q - zero_point) * scale


def quantize_blockwise(x, bits: int, block: int = BLOCK):
    """ブロックごとにスケールを持つ対称量子化（K 系の発想の最小版）。"""
    qmax = 2 ** (bits - 1) - 1
    flat = np.asarray(x, dtype=np.float64).reshape(-1)
    pad = (-flat.size) % block
    padded = np.concatenate([flat, np.zeros(pad)]) if pad else flat
    blocks = padded.reshape(-1, block)
    scales = np.abs(blocks).max(axis=1, keepdims=True) / qmax
    scales[scales == 0] = 1.0
    deq = np.clip(np.rint(blocks / scales), -qmax - 1, qmax) * scales
    return deq.reshape(-1)[: flat.size], scales.reshape(-1)


def rmse(a, b) -> float:
    return float(np.sqrt(np.mean((np.asarray(a, dtype=np.float64) - np.asarray(b)) ** 2)))


# --- 1. 量子化の式（スケールとゼロ点） -------------------------------------
print("=== 1. 量子化の式（スケールとゼロ点） ===")
rng = np.random.default_rng(SEED)
w = rng.normal(0.0, 0.02, 4096)          # 重みらしい分布（平均0・小さな散らばり）

max_errors: dict[int, float] = {}
for bits in (8, 4):
    _, scale, deq = quantize_symmetric(w, bits)
    max_err = float(np.abs(w - deq).max())
    max_errors[bits] = max_err
    print(f"  int{bits} 対称: scale={scale:.3e}  最大誤差={max_err:.3e}  "
          f"(scale/2={scale / 2:.3e})  RMSE={rmse(w, deq):.3e}")
    check(f"int{bits} 対称量子化の最大誤差が scale/2 以下",
          max_err <= scale / 2 * (1 + 1e-6), f"{max_err:.3e} <= {scale / 2:.3e}")

ratio = max_errors[4] / max_errors[8]
check("int4 の誤差は int8 の約18倍（scale が 127/7 倍になるため）",
      10.0 < ratio < 25.0, f"{ratio:.1f} 倍（理論値 {127 / 7:.1f} 倍）")

shifted = rng.uniform(2.0, 3.0, 4096)    # 正の狭い範囲に偏った分布
_, sym_scale, sym_deq = quantize_symmetric(shifted, 8)
_, aff_scale, aff_zp, aff_deq = quantize_affine(shifted, 8)
print(f"  2.0〜3.0 に偏った配列: 対称 scale={sym_scale:.3e} RMSE={rmse(shifted, sym_deq):.3e}  /  "
      f"非対称 scale={aff_scale:.3e} zp={aff_zp} RMSE={rmse(shifted, aff_deq):.3e}")
check("ゼロ点つき（非対称）は正の狭い範囲で対称より誤差が小さい",
      rmse(shifted, aff_deq) * 3 < rmse(shifted, sym_deq),
      f"{rmse(shifted, sym_deq):.3e} -> {rmse(shifted, aff_deq):.3e}")

hand = np.array([-1.0, 0.0, 0.5, 1.5, 3.0])
q_hand, h_scale, h_zp, h_deq = quantize_affine(hand, 8)
print(f"  手計算例 [-1.0 .. 3.0]: scale={h_scale:.6f} zero_point={h_zp} "
      f"q={[int(v) for v in q_hand]}")
print(f"    逆量子化: {[round(float(v), 4) for v in h_deq]}")
check("手計算例の scale が 4/255・zero_point が 64・両端が 0 と 255 になる",
      abs(h_scale - 4 / 255) < 1e-12 and h_zp == 64
      and int(q_hand.min()) == 0 and int(q_hand.max()) == 255,
      f"scale={h_scale:.6f} zp={h_zp} q=[{int(q_hand.min())}..{int(q_hand.max())}]")
check("非対称量子化の誤差も scale/2 以下",
      float(np.abs(hand - h_deq).max()) <= h_scale / 2 * (1 + 1e-6),
      f"{float(np.abs(hand - h_deq).max()):.3e} <= {h_scale / 2:.3e}")

# --- 2. ブロック単位の量子化は外れ値に強い ---------------------------------
print("\n=== 2. ブロック単位の量子化は外れ値に強い ===")
weights = rng.normal(0.0, 0.02, 1024)
weights[500] = 5.0                        # 外れ値を1つだけ混ぜる
print(f"  配列 {weights.size} 要素 / 外れ値 1 個（index 500 = {weights[500]}）")

for bits in (8, 4):
    _, tensor_scale, per_tensor = quantize_symmetric(weights, bits)
    block_deq, scales = quantize_blockwise(weights, bits)
    e_all, e_blk = rmse(weights, per_tensor), rmse(weights, block_deq)
    print(f"  int{bits}: 全体1スケール(scale={tensor_scale:.3e}) RMSE={e_all:.3e}  /  "
          f"{BLOCK}要素ブロック({len(scales)}個) RMSE={e_blk:.3e}")
    check(f"int{bits}：ブロック単位はテンソル全体より外れ値に強い（RMSE が3分の1未満）",
          e_blk * 3 < e_all, f"{e_all:.3e} -> {e_blk:.3e}")

overhead = 16 / BLOCK
print(f"  ブロックごとに fp16 スケールを1つ持つ追加コスト: 16/{BLOCK} = {overhead} ビット/重み")
check("32要素ブロック＋fp16スケールの実効ビットが 8.5（Q8_0 の定義と一致）",
      8 + overhead == 8.5, f"8 + {overhead} = {8 + overhead} ビット/重み")
check("4ビットでも同じ追加コストで実効 4.5 ビット（Q4_0・Q4_K の公称値）",
      4 + overhead == 4.5, f"4 + {overhead} = {4 + overhead} ビット/重み")

# --- 3. GGUF ファイルのサイズ（あれば） ------------------------------------
print("\n=== 3. GGUF ファイルのサイズ（あれば） ===")
gguf_files = sorted(GGUF_DIR.glob("*.gguf")) if GGUF_DIR.exists() else []
if not gguf_files:
    print("  gguf/ に .gguf がありません（まだ変換していません）。")
    print("  本文の手順で変換してから再実行してください:")
    print("    docker compose run --rm llamacpp --convert --outtype f16 /work/export/qwen05b")
else:
    f16 = next((p for p in gguf_files if "f16" in p.name.lower()),
               max(gguf_files, key=lambda p: p.stat().st_size))
    base_mb = f16.stat().st_size / 1024 / 1024
    print(f"  基準（f16）: {f16.name}")
    print(f"  {'ファイル':<34}{'サイズ(MB)':>12}{'f16比':>9}{'実効bit':>9}")
    for path in sorted(gguf_files, key=lambda p: -p.stat().st_size):
        mb = path.stat().st_size / 1024 / 1024
        print(f"  {path.name:<34}{mb:>12.1f}{mb / base_mb * 100:>8.1f}%{16 * mb / base_mb:>9.2f}")
    check("すべての .gguf が 1MB を超えている（変換が途中で切れていない）",
          all(p.stat().st_size > 1024 * 1024 for p in gguf_files), f"{len(gguf_files)} 個")
    q4_files = [p for p in gguf_files if "q4" in p.name.lower()]
    if q4_files:
        check("Q4 系は f16 より小さい",
              all(p.stat().st_size < f16.stat().st_size for p in q4_files),
              f"{[p.name for p in q4_files]}")

# --- 4. 統合済みモデルの書き出し（GGUF 変換の入力を作る） -------------------
print("\n=== 4. 統合済みモデルの書き出し（GGUF 変換の入力を作る） ===")
if os.environ.get("SKIP_MERGE") == "1":
    print("  SKIP_MERGE=1 のため飛ばします（モデルを読みません）。")
else:
    from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer, param_stats  # noqa: E402
    from ftkit.quantize import save_merged  # noqa: E402
    from ftkit.train import set_seed  # noqa: E402

    tokenizer = load_tokenizer(FAST_MODEL)
    set_seed(SEED)                        # モデル構築の前に呼ぶ
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    stats = param_stats(model)
    print(f"  学習対象 {stats['trainable']:,} / 全体 {stats['total']:,} "
          f"({stats['ratio'] * 100:.2f}%) — 学習はせず差分ゼロのまま統合する")

    merged_dir = save_merged(model, tokenizer, "session10-135m")
    merged_mb = dir_size_mb(merged_dir)
    names = sorted(p.name for p in merged_dir.iterdir())
    print(f"  {merged_dir}  {merged_mb:.1f} MB")
    print(f"  ファイル: {names}")
    check("統合済みモデルに config.json と重みファイルがある",
          "config.json" in names and any(n.endswith(".safetensors") for n in names), str(names))
    check("トークナイザも一緒に保存されている（変換に必要）",
          any(n.startswith("tokenizer") for n in names), str(names))
    check("サイズが fp32 135M 相当（400MB 超・アダプタ約3.5MB の100倍以上）",
          merged_mb > 400, f"{merged_mb:.1f} MB")

    del model
    gc.collect()
    print("  Python を終了させたうえで、別コンテナで変換します:")
    print("    docker compose run --rm llamacpp --convert --outtype f16 "
          "/work/export/session10-135m")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション10の検証はすべて成功しました。")
