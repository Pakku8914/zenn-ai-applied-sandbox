#!/usr/bin/env python3
"""案B：端末上の ONNX int8 分類器で一次分類する（中間プロジェクト2）。

    python src/mid02/edge_side.py                 # サイズ・速度・精度・マージン
    python src/mid02/edge_side.py --threads 1 2   # スレッド数を振る

セッション12 の判定条件（確率の最大差とマージン別の一致率）を、
**この章の 20 件の入力に対して**適用する。乱数入力ではなく実際の入力で見るのが
違いで、配るモデルの合否はこちらで判断する。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.edge import bench_session, file_size_mb, first_inference_ms, make_session  # noqa: E402
from src.mid02.task import PROTOCOL, feature_matrix  # noqa: E402
from src.session12.quant_report import ONNX_DIR, ensure_fp32, quantize  # noqa: E402
from tools.prompts import QUESTIONS  # noqa: E402

REPORTS = SANDBOX / "reports"
RUNTIME_MB = 50.0
"""③ 前提値。分類器だけの実行時メモリ（セッション11 で置いた値）。"""

DEVICE_D_LIMIT_MB = 512.0
"""③ 前提値。端末D の「推論に使える上限」（セッション11）。"""

MARGIN = 0.05
"""「はっきりしている」と見なす1位と2位の確率の差（セッション12 と同じ）。"""

MAX_DIFF_LIMIT = 0.01
"""許容する確率の最大差（セッション12 と同じ）。"""


@dataclass(frozen=True)
class EdgeDecision:
    """案Aの Decision と**同じ形**にする（比較の前提）。"""

    index: int
    category_id: int
    confidence: float     # softmax の最大値
    margin: float         # 1位と2位の差。ハイブリッドの振り分けに使う

    @property
    def parsed(self) -> bool:
        return True       # 構造的に必ず 6 クラスの確率が返る（形式違反が無い）


@dataclass(frozen=True)
class Equivalence:
    """fp32 を基準に int8 を比べた結果。**際どい件の入れ替わりは不合格にしない。**"""

    samples: int
    max_diff: float
    median_diff: float
    agree: int
    clear_total: int
    clear_agree: int
    close_total: int
    close_agree: int
    margin: float = MARGIN
    max_diff_limit: float = MAX_DIFF_LIMIT

    @property
    def passed(self) -> bool:
        return (self.max_diff <= self.max_diff_limit
                and self.clear_agree == self.clear_total)


def ensure_pair() -> tuple[Path, Path]:
    """fp32 と int8 を用意する（無ければ作る。外部ダウンロードは無い）。"""
    fp32 = ensure_fp32()
    int8 = ONNX_DIR / "classifier_int8.onnx"
    if not int8.exists():
        quantize(fp32, int8)
    return fp32, int8


def probabilities(model: Path, threads: int = 1,
                  questions=QUESTIONS) -> np.ndarray:
    """20 件ぶんの確率。**入力は featurize で決定的に作る**（誰の環境でも同じ）。"""
    session = make_session(model, threads)
    feats = feature_matrix(questions)
    return np.stack([session.run(None, {"input": feats[i:i + 1]})[0][0]
                     for i in range(len(feats))])


def decisions(probs: np.ndarray) -> tuple[EdgeDecision, ...]:
    out: list[EdgeDecision] = []
    for i, row in enumerate(probs):
        order = np.argsort(row)[::-1]
        out.append(EdgeDecision(i, int(order[0]), float(row[order[0]]),
                                float(row[order[0]] - row[order[1]])))
    return tuple(out)


def equivalence(p32: np.ndarray, p8: np.ndarray, margin: float = MARGIN,
                max_diff_limit: float = MAX_DIFF_LIMIT) -> Equivalence:
    diffs = np.abs(p32 - p8).max(axis=1)
    d32, d8 = decisions(p32), decisions(p8)
    agrees = [a.category_id == b.category_id for a, b in zip(d32, d8)]
    clear = [a for a, d in zip(agrees, d32) if d.margin >= margin]
    close = [a for a, d in zip(agrees, d32) if d.margin < margin]
    return Equivalence(
        samples=len(agrees), max_diff=float(diffs.max()),
        median_diff=float(np.median(diffs)), agree=sum(agrees),
        clear_total=len(clear), clear_agree=sum(clear),
        close_total=len(close), close_agree=sum(close),
        margin=margin, max_diff_limit=max_diff_limit)


def footprint_mb(int8_size_mb: float, runtime_mb: float = RUNTIME_MB) -> dict:
    """端末に載るか。**KVキャッシュは 0**（分類器なので保持する状態が無い）。"""
    return {"weights_mb": int8_size_mb, "kv_mb": 0.0, "runtime_mb": runtime_mb,
            "total_mb": int8_size_mb + runtime_mb}


def bench(model: Path, threads: int, repeats: int = 50) -> dict:
    feats = feature_matrix()
    feeds = {"input": feats[0:1]}
    first = first_inference_ms(model, feeds, threads)
    result = bench_session(make_session(model, threads), feeds, model.stem,
                           model, threads, repeats=repeats)
    return {"threads": threads, "first_ms": round(first, 3),
            "p50_ms": round(result.latency_ms["p50"], 3),
            "p95_ms": round(result.latency_ms["p95"], 3)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="案B：エッジで一次分類する")
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=3,
                        help="スレッド数の比較を何回繰り返すか（1回で順位を語らない）")
    parser.add_argument("--out", default="reports/mid02_edge.json")
    args = parser.parse_args(argv)

    import onnxruntime as ort

    fp32, int8 = ensure_pair()
    size32, size8 = file_size_mb(fp32), file_size_mb(int8)

    print("=== 決定的な値（誰の環境でも同じ）===")
    print("| 形式 | サイズ | fp32 比 |")
    print("| :--- | --: | --: |")
    print(f"| fp32 | {size32:.2f} MB | 100.0% |")
    print(f"| int8 | {size8:.2f} MB | {size8 / size32:.1%} |")
    fp = footprint_mb(size8)
    print(f"端末の占有: 重み {fp['weights_mb']:.2f} + KVキャッシュ "
          f"{fp['kv_mb']:.2f} + 実行時 {fp['runtime_mb']:.2f} = "
          f"{fp['total_mb']:.2f} MB")
    print(f"  端末D（上限 {DEVICE_D_LIMIT_MB:.1f} MB・セッション11 の前提値）"
          "に収まるか: "
          + ("はい" if fp["total_mb"] <= DEVICE_D_LIMIT_MB else "いいえ"))

    print("\n=== この環境の値（実行ごとに揺れます）===")
    benches = [bench(int8, t, args.repeats)
               for _ in range(args.rounds) for t in args.threads]
    print("| スレッド | 定常 p50 | 定常 p95 | 初回推論 |")
    print("| --: | --: | --: | --: |")
    for row in benches:
        print(f"| {row['threads']} | {row['p50_ms']:.2f} ms | "
              f"{row['p95_ms']:.2f} ms | {row['first_ms']:.2f} ms |")
    if args.rounds < 3:
        print(f"  注意: {args.rounds} 回しか測っていません。"
              "1 回の測定でスレッド数の順位を語らないこと。")

    p32 = probabilities(fp32, args.threads[0])
    p8 = probabilities(int8, args.threads[0])
    eq = equivalence(p32, p8)
    d8 = decisions(p8)
    margins = sorted(d.margin for d in d8)
    print("\n=== 同値性（fp32 を基準に int8 を比べる。20 件の実入力）===")
    print(f"確率の最大差   : 最大 {eq.max_diff:.6f} / 中央 {eq.median_diff:.6f}")
    print(f"最大クラスの一致: {eq.agree} / {eq.samples} 件")
    print(f"  マージン {eq.margin:.2f} 以上: "
          f"{eq.clear_agree} / {eq.clear_total} 件")
    print(f"  マージン {eq.margin:.2f} 未満: "
          f"{eq.close_agree} / {eq.close_total} 件  <- 入れ替わるのはここ")
    print(f"判定           : {'合格' if eq.passed else '不合格'}"
          f"（条件: 最大差 <= {eq.max_diff_limit:.3f} かつ "
          f"マージン {eq.margin:.2f} 以上は全件一致）")
    print(f"マージンの分布 : 最小 {margins[0]:.4f} / "
          f"中央 {statistics.median(margins):.4f} / 最大 {margins[-1]:.4f}")
    print("\n注意: このモデルは tools/make_edge_model.py が固定シードで組み立てた"
          "**学習していない雛形**です。")
    print("      参照ラベルに対する正解率は意味を持ちません。作るのは枠組みです。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "conditions": {
            "side": "edge", "date": str(date.today()),
            "machine": platform.machine(), "cpu_count": os.cpu_count(),
            "onnxruntime": ort.__version__,
            "input_set": "tools/prompts.py:QUESTIONS", "n_inputs": len(QUESTIONS),
            "output_form": "category_id+confidence",
            "measure_point": "区分IDを受け取るまで",
            # median_of は「代表値を何回測って中央値を採ったか」（取り決め6）。
            # 1 回の計測の中の繰り返し回数（bench_repeats）とは別物なので分けて書く。
            "median_of": args.rounds, "bench_repeats": args.repeats,
            "warmup": 3,
            "model": f"classifier_int8.onnx({size8:.2f}MB)",
            "network_roundtrip": "含まない",
            "protocol": {k: v for k, v in PROTOCOL},
        },
        "size_mb": {"fp32": round(size32, 2), "int8": round(size8, 2),
                    "ratio": round(size8 / size32, 4)},
        "footprint_mb": fp, "bench": benches,
        "equivalence": {"max_diff": eq.max_diff, "median_diff": eq.median_diff,
                        "agree": eq.agree, "samples": eq.samples,
                        "clear": [eq.clear_agree, eq.clear_total],
                        "close": [eq.close_agree, eq.close_total],
                        "passed": eq.passed},
        "margins": [round(d.margin, 6) for d in d8],
        "decisions": [{"index": d.index, "category_id": d.category_id,
                       "confidence": round(d.confidence, 6),
                       "margin": round(d.margin, 6)} for d in d8],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
