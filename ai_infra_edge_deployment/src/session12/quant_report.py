#!/usr/bin/env python3
"""サイズ・速度・精度を1つの表にする（セッション12）。

  python src/session12/quant_report.py
  python src/session12/quant_report.py --repeats 100 --threads 1

3点のうち1つでも欠けたら、量子化の可否は判断できない。

  ・サイズ : 端末に載るか（前章の予算に効く）
  ・速度   : 間に合うか
  ・精度   : 使えるか（最大クラスの一致と、確率の最大差の2つで見る）

「小さくなりました」だけの報告は、受け取った側が何も判断できない。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import onnx

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.edge import bench_session, file_size_mb, first_inference_ms, make_session  # noqa: E402

ONNX_DIR = SANDBOX / "models" / "onnx"
REPORTS = SANDBOX / "reports"
SEED = 20260815
INPUT_DIM = 384
QUANT_HINTS = ("Quantize", "Integer", "QLinear")


def ensure_fp32(hidden: int = 4096, name: str = "classifier_fp32") -> Path:
    """fp32 の ONNX を用意する（無ければ決定的に作る）。"""
    path = ONNX_DIR / f"{name}.onnx"
    if not path.exists():
        from tools.make_edge_model import build
        build(hidden, name)
    return path


def quantize(src: Path, dst: Path) -> float:
    """動的量子化。**重みは今ここで int8 になる**（実行時に変換されるのではない）。

    「動的」なのは、入力（活性値）のスケールを実行時に決めるという意味である。
    キャリブレーション用のデータを用意しなくてよいのが、この方式の利点。
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic

    t0 = time.perf_counter()
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    return time.perf_counter() - t0


def node_count(path: Path) -> int:
    return len(onnx.load(str(path)).graph.node)


def quant_node_count(path: Path) -> int:
    model = onnx.load(str(path))
    return sum(1 for n in model.graph.node
               if any(hint in n.op_type for hint in QUANT_HINTS))


def fixed_input() -> dict[str, np.ndarray]:
    """毎回同じ入力を使う。条件を揃えないと比較できない（セッション2の規約）。"""
    rng = np.random.default_rng(SEED)
    return {"input": rng.normal(size=(1, INPUT_DIM)).astype(np.float32)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()

    import onnxruntime as ort

    fp32 = ensure_fp32()
    int8 = ONNX_DIR / "classifier_int8.onnx"
    quant_seconds = quantize(fp32, int8)

    feeds = fixed_input()
    size32, size8 = file_size_mb(fp32), file_size_mb(int8)
    first32 = first_inference_ms(fp32, feeds, args.threads)
    first8 = first_inference_ms(int8, feeds, args.threads)
    bench32 = bench_session(make_session(fp32, args.threads), feeds, "fp32", fp32,
                            args.threads, repeats=args.repeats)
    bench8 = bench_session(make_session(int8, args.threads), feeds, "int8", int8,
                           args.threads, repeats=args.repeats)

    ref = make_session(fp32, args.threads).run(None, feeds)[0]
    got = make_session(int8, args.threads).run(None, feeds)[0]
    diff = float(np.abs(ref - got).max())
    same_argmax = int(np.argmax(ref)) == int(np.argmax(got))

    print("=== サイズ・速度・精度（1つの表で語る）===\n")
    print("| 形式 | サイズ | fp32 比 | 定常 p50 | 初回推論 | 最大クラス | 確率の最大差 |")
    print("| :--- | --: | --: | --: | --: | :--- | --: |")
    print(f"| fp32 | {size32:.2f} MB | 100.0% | {bench32.latency_ms['p50']:.2f} ms | "
          f"{first32:.2f} ms | 基準 | — |")
    print(f"| int8 | {size8:.2f} MB | {size8 / size32:.1%} | "
          f"{bench8.latency_ms['p50']:.2f} ms | {first8:.2f} ms | "
          f"{'一致' if same_argmax else '不一致'} | {diff:.6f} |")
    print(f"\n測定条件: {date.today()} / {platform.machine()} / CPU {os.cpu_count()}コア / "
          f"onnxruntime {ort.__version__} / スレッド{args.threads} / "
          f"{args.repeats}回の中央値 / 入力は seed {SEED} の固定値")

    n32, n8 = node_count(fp32), node_count(int8)
    print("\n=== グラフの変化（fp32 -> int8）===")
    print(f"重みの持ち方         : fp32 の {size8 / size32:.1%}（int8 に置き換わった）")
    print("量子化に関わるノード : "
          + ("入っている" if quant_node_count(int8) > 0 else "入っていない"))
    print("ノードの数           : fp32 より"
          + ("増えている（量子化と逆量子化が挟まる）" if n8 > n32 else "増えていない"))
    print("-> 小さくなってもノードは増える。"
          "サイズが減れば速くなる、とは言えない理由がこれ。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_quant.json"
    out.write_text(json.dumps({
        "date": str(date.today()), "machine": platform.machine(),
        "cpu_count": os.cpu_count(), "onnxruntime": ort.__version__,
        "threads": args.threads, "repeats": args.repeats,
        "quant_seconds": round(quant_seconds, 2),
        "fp32": {"size_mb": round(size32, 2), "first_ms": round(first32, 2),
                 "p50_ms": round(bench32.latency_ms["p50"], 3)},
        "int8": {"size_mb": round(size8, 2), "first_ms": round(first8, 2),
                 "p50_ms": round(bench8.latency_ms["p50"], 3),
                 "size_ratio": round(size8 / size32, 4)},
        "accuracy": {"max_prob_diff": diff, "same_argmax": same_argmax},
        "graph": {"nodes_fp32": n32, "nodes_int8": n8,
                  "quant_nodes_int8": quant_node_count(int8)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
