#!/usr/bin/env python3
"""「そもそも測れる規模か」を先に確かめる（セッション12）。

  python src/session12/scale_check.py
  python src/session12/scale_check.py --hidden 4096 --repeats 100

小さすぎるモデルで測ると、定常レイテンシがサブミリ秒になり、初回推論との比が
実行ごとに大きく揺れる。**その規模で性能を語ってはいけない。**
量子化の速度差を語る前に、まずこのスクリプトで「語ってよい規模か」を確かめる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.edge import bench_session, file_size_mb, first_inference_ms, make_session  # noqa: E402

ONNX_DIR = SANDBOX / "models" / "onnx"
REPORTS = SANDBOX / "reports"
SEED = 20260815
INPUT_DIM = 384
N_CLASSES = 6

FLOOR_MS = 1.0    # これ以上あれば、量子化の速度差を語ってよい
NOISE_MS = 0.5    # これ未満は測定ノイズに埋もれている


def params(hidden: int) -> int:
    """重み行列の要素数（バイアスは含めない。tools/make_edge_model.py と同じ数え方）。"""
    return INPUT_DIM * hidden + hidden * hidden + hidden * N_CLASSES


def ensure_model(hidden: int) -> Path:
    """その規模の fp32 モデルを用意する（無ければ決定的に作る）。"""
    name = "classifier_fp32" if hidden == 4096 else f"classifier_h{hidden}"
    path = ONNX_DIR / f"{name}.onnx"
    if not path.exists():
        from tools.make_edge_model import build
        build(hidden, name)
    return path


def verdict(p50: float) -> str:
    if p50 >= FLOOR_MS:
        return "語ってよい"
    if p50 >= NOISE_MS:
        return "境界（回数を増やして分布を見る）"
    return "ノイズに埋もれる"


def measure(path: Path, threads: int = 1, repeats: int = 50) -> tuple[float, float]:
    """(定常 p50, 初回推論) を返す。ウォームアップは infrakit 側で行われる。"""
    rng = np.random.default_rng(SEED)
    feeds = {"input": rng.normal(size=(1, INPUT_DIM)).astype(np.float32)}
    first = first_inference_ms(path, feeds, threads)
    bench = bench_session(make_session(path, threads), feeds, path.stem, path,
                          threads, repeats=repeats)
    return bench.latency_ms["p50"], first


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hidden", type=int, nargs="+", default=[512, 1536, 4096])
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()

    paths = {h: ensure_model(h) for h in args.hidden}

    print("=== モデルの一覧（サイズは誰の環境でも同じ値になります）===")
    print("| 隠れ層 | パラメータ | fp32 のサイズ |")
    print("| --: | --: | --: |")
    for h in args.hidden:
        print(f"| {h} | {params(h) / 1e6:.2f}M | {file_size_mb(paths[h]):.2f} MB |")

    print("\n=== 測定（この環境の値。レイテンシは実行ごとに揺れます）===")
    print("| 隠れ層 | 定常 p50 | 初回推論 | 初回/定常 | 判定 |")
    print("| --: | --: | --: | --: | :--- |")
    rows = []
    for h in args.hidden:
        p50, first = measure(paths[h], args.threads, args.repeats)
        ratio = first / max(p50, 1e-9)
        rows.append({"hidden": h, "size_mb": round(file_size_mb(paths[h]), 2),
                     "p50_ms": round(p50, 3), "first_ms": round(first, 3),
                     "ratio": round(ratio, 2), "verdict": verdict(p50)})
        print(f"| {h} | {p50:.2f} ms | {first:.2f} ms | {ratio:.1f} 倍 | {verdict(p50)} |")

    print(f"\n-> 定常 p50 が {FLOOR_MS:.2f} ms 以上ある規模でだけ、"
          "量子化の速度差を語ってよい。")
    print(f"-> {NOISE_MS:.2f} ms 未満の規模で出した「N 倍速い」は、"
          "次の実行で別の数字になる。")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "bench_edge_scale.json"
    out.write_text(json.dumps(
        {"threads": args.threads, "repeats": args.repeats,
         "floor_ms": FLOOR_MS, "noise_ms": NOISE_MS, "rows": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(SANDBOX)}")


if __name__ == "__main__":
    main()
