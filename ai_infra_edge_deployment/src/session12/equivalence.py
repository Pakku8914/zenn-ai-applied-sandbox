#!/usr/bin/env python3
"""変換後のモデルが「同じ」かを確かめる（セッション12）。

  python src/session12/equivalence.py
  python src/session12/equivalence.py --samples 256 --margin 0.05

精度を語るときは**2つの指標を必ずセットで**見る。

  ① 最大クラスが一致するか   -> 判断が変わったか
  ② 確率の最大差             -> 判断の確度がどれだけ動いたか

①だけ見て「同じでした」と言うと、しきい値で分岐する処理（確度 0.8 以上なら
自動処理、など）を静かに壊す。②だけ見ても、判断が入れ替わったかは分からない。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from infrakit.edge import make_session  # noqa: E402
from quant_report import ONNX_DIR, REPORTS, SEED, ensure_fp32, quantize  # noqa: E402

INPUT_DIM = 384


@dataclass(frozen=True)
class Equivalence:
    samples: int
    max_diff: float
    median_diff: float
    agree: int
    margin: float          # 「はっきりしている」と見なす1位と2位の差
    clear_total: int       # マージンが閾値以上の件数
    clear_agree: int
    close_total: int       # マージンが閾値未満の件数（際どいサンプル）
    close_agree: int
    max_diff_limit: float

    @property
    def passed(self) -> bool:
        """合否の条件。**際どいサンプルの入れ替わりは不合格にしない。**

        マージンが 0 に近いサンプルは、量子化しなくても入力のわずかな違いで
        入れ替わる。そこを不合格にすると、正しい量子化を捨てることになる。
        """
        return self.max_diff <= self.max_diff_limit and self.clear_agree == self.clear_total

    def summary(self) -> str:
        return (f"最大差 {self.max_diff:.6f} / 一致 {self.agree}/{self.samples} / "
                f"判定 {'合格' if self.passed else '不合格'}")


def compare(samples: int = 64, margin: float = 0.05,
            max_diff_limit: float = 0.01,
            fp32: Path | None = None, int8: Path | None = None) -> Equivalence:
    fp32 = fp32 or ensure_fp32()
    int8 = int8 or ONNX_DIR / "classifier_int8.onnx"
    if not int8.exists():
        quantize(fp32, int8)

    rng = np.random.default_rng(SEED)
    xs = rng.normal(size=(samples, INPUT_DIM)).astype(np.float32)
    s32, s8 = make_session(fp32, 1), make_session(int8, 1)

    diffs: list[float] = []
    margins: list[float] = []
    agrees: list[bool] = []
    for i in range(samples):
        feeds = {"input": xs[i:i + 1]}
        ref = s32.run(None, feeds)[0][0]
        got = s8.run(None, feeds)[0][0]
        diffs.append(float(np.abs(ref - got).max()))
        ordered = np.sort(ref)[::-1]
        margins.append(float(ordered[0] - ordered[1]))
        agrees.append(int(np.argmax(ref)) == int(np.argmax(got)))

    clear = [a for a, m in zip(agrees, margins) if m >= margin]
    close = [a for a, m in zip(agrees, margins) if m < margin]
    return Equivalence(
        samples=samples, max_diff=max(diffs), median_diff=float(np.median(diffs)),
        agree=sum(agrees), margin=margin,
        clear_total=len(clear), clear_agree=sum(clear),
        close_total=len(close), close_agree=sum(close),
        max_diff_limit=max_diff_limit)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--margin", type=float, default=0.05,
                    help="1位と2位の確率の差。これ以上なら『はっきりしている』と見なす")
    ap.add_argument("--max-diff", type=float, default=0.01,
                    help="許容する確率の最大差")
    args = ap.parse_args()

    fp32 = ensure_fp32()
    int8 = ONNX_DIR / "classifier_int8.onnx"
    quantize(fp32, int8)

    # 1件目だけは tools/bench_edge.py と同じ入力になる（同じ seed の先頭 384 個）
    one = compare(samples=1, margin=args.margin, max_diff_limit=args.max_diff,
                  fp32=fp32, int8=int8)
    print("=== 等価性の検証（fp32 を基準に int8 を比べる）===")
    print(f"入力        : seed {SEED} の正規乱数 {args.samples} 件（誰の環境でも同じ入力）")
    print(f"判定の条件  : 確率の最大差 <= {args.max_diff:.3f} かつ "
          f"マージン {args.margin:.2f} 以上のサンプルは全件一致")
    print(f"1件目の結果 : 確率の最大差 {one.max_diff:.6f} / "
          f"最大クラス {'一致' if one.agree == 1 else '不一致'}")

    eq = compare(samples=args.samples, margin=args.margin,
                 max_diff_limit=args.max_diff, fp32=fp32, int8=int8)
    print(f"\n確率の最大差 : 最大 {eq.max_diff:.6f} / 中央 {eq.median_diff:.6f}")
    print(f"最大クラスの一致: {eq.agree} / {eq.samples} 件")
    print(f"  マージン {eq.margin:.2f} 以上 : {eq.clear_agree} / {eq.clear_total} 件が一致")
    print(f"  マージン {eq.margin:.2f} 未満 : {eq.close_agree} / {eq.close_total} 件が一致"
          "  <- 入れ替わるのはここ")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_equivalence.json"
    out.write_text(json.dumps({
        "samples": eq.samples, "margin": eq.margin,
        "max_diff": eq.max_diff, "median_diff": eq.median_diff,
        "max_diff_limit": eq.max_diff_limit,
        "agree": eq.agree, "clear": [eq.clear_agree, eq.clear_total],
        "close": [eq.close_agree, eq.close_total], "passed": eq.passed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n判定: {'合格' if eq.passed else '不合格'}"
          f"（条件：確率の最大差 <= {eq.max_diff_limit:.3f} / "
          f"マージン {eq.margin:.2f} 以上のサンプルは全件一致）")
    print(f"-> {out.relative_to(SANDBOX)}")
    if not eq.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
