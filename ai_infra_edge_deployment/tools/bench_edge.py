#!/usr/bin/env python3
"""エッジ推論の実測（セッション12・13の実測値の出典）。

fp32 と int8 のサイズ・レイテンシ・出力差を測り、スレッド数を振って最適点を探す。

  python tools/bench_edge.py
  python tools/bench_edge.py --threads 1 2 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrakit.edge import bench_session, file_size_mb, first_inference_ms, make_session  # noqa: E402

SANDBOX = Path(__file__).resolve().parent.parent
ONNX_DIR = SANDBOX / "models" / "onnx"
REPORTS = SANDBOX / "reports"
SEED = 20260815
INPUT_DIM = 384


def quantize(src: Path, dst: Path) -> float:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    t0 = time.perf_counter()
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    return time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--repeats", type=int, default=50)
    args = ap.parse_args()

    fp32 = ONNX_DIR / "classifier_fp32.onnx"
    if not fp32.exists():
        print("先に `python tools/make_edge_model.py` を実行してください。")
        sys.exit(1)

    int8 = ONNX_DIR / "classifier_int8.onnx"
    quant_seconds = quantize(fp32, int8)
    print("=== モデルサイズ ===")
    print(f"fp32 : {file_size_mb(fp32):>8.2f} MB")
    print(f"int8 : {file_size_mb(int8):>8.2f} MB "
          f"（{file_size_mb(int8) / file_size_mb(fp32) * 100:.1f}% ・変換 {quant_seconds:.1f}s）")

    rng = np.random.default_rng(SEED)
    x = rng.normal(size=(1, INPUT_DIM)).astype(np.float32)
    feeds = {"input": x}

    print("\n=== 初回推論と定常時の差（スレッド1）===")
    for label, path in (("fp32", fp32), ("int8", int8)):
        first = first_inference_ms(path, feeds, threads=1)
        session = make_session(path, 1)
        steady = bench_session(session, feeds, label, path, 1, repeats=args.repeats)
        print(f"{label}: 初回 {first:>8.2f}ms / 定常 p50 {steady.latency_ms['p50']:>7.2f}ms "
              f"（{first / max(steady.latency_ms['p50'], 1e-9):.1f} 倍）")

    # fp32 の出力を基準に int8 の出力差を測る（精度劣化の代理指標）
    ref = make_session(fp32, 1).run(None, feeds)[0]
    got = make_session(int8, 1).run(None, feeds)[0]
    diff = float(np.abs(ref - got).max())
    same_argmax = int(np.argmax(ref)) == int(np.argmax(got))
    print(f"\n=== 出力の一致 ===")
    print(f"確率の最大差   : {diff:.6f}")
    print(f"最大クラスが一致: {'はい' if same_argmax else 'いいえ'}")

    print("\n=== スレッド数を振る ===")
    print(f"{'モデル':<8}{'スレッド':>8}{'p50(ms)':>10}{'p95(ms)':>10}{'min(ms)':>10}")
    results = []
    for label, path in (("fp32", fp32), ("int8", int8)):
        for threads in args.threads:
            session = make_session(path, threads)
            bench = bench_session(session, feeds, label, path, threads, repeats=args.repeats)
            results.append(bench)
            print(f"{label:<8}{threads:>8}{bench.latency_ms['p50']:>10.2f}"
                  f"{bench.latency_ms['p95']:>10.2f}{bench.latency_ms['min']:>10.2f}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "edge_bench.json").write_text(json.dumps(
        {"fp32_mb": round(file_size_mb(fp32), 3), "int8_mb": round(file_size_mb(int8), 3),
         "quant_seconds": round(quant_seconds, 2), "max_prob_diff": diff,
         "same_argmax": same_argmax,
         "runs": [{"label": r.label, "threads": r.threads, **r.latency_ms} for r in results]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n-> reports/edge_bench.json")

    shutil.rmtree(ONNX_DIR / "__pycache__", ignore_errors=True)


if __name__ == "__main__":
    main()
