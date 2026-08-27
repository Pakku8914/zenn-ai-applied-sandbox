#!/usr/bin/env python3
"""ONNX ファイルの中身を覗く（セッション12）。

  python src/session12/inspect_onnx.py                                # 既定は fp32 の分類器
  python src/session12/inspect_onnx.py models/onnx/classifier_int8.onnx

ONNX は「実行環境から独立したモデルの表現」である。中身は演算子のグラフと
重みの塊なので、変換が思ったとおりに終わったかは**ファイルを開けば分かる**。
変換で困ったとき、最初に見るのはランタイムのログではなくここである。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import onnx
from onnx import numpy_helper

SANDBOX = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = SANDBOX / "models" / "onnx" / "classifier_fp32.onnx"
MB = 1024 ** 2

# 量子化に関わる演算子は「名前に含まれる語」で見分ける。生成される演算子名は
# onnxruntime のバージョンで変わるため、完全一致では拾えない。
QUANT_HINTS = ("Quantize", "Integer", "QLinear")


def shape_text(value_info) -> str:
    """形状を文字列にする。固定なら数字、動的なら次元の名前（"batch" など）が入る。"""
    dims = []
    for d in value_info.type.tensor_type.shape.dim:
        dims.append(d.dim_param if d.dim_param else str(d.dim_value))
    return "[" + ", ".join(dims) + "]"


def dtype_text(value_info) -> str:
    return onnx.TensorProto.DataType.Name(value_info.type.tensor_type.elem_type)


def op_counts(model) -> dict[str, int]:
    """演算子の内訳。ここが変換の結果そのものである。"""
    counts: dict[str, int] = {}
    for node in model.graph.node:
        counts[node.op_type] = counts.get(node.op_type, 0) + 1
    return dict(sorted(counts.items()))


def quant_nodes(model) -> int:
    return sum(1 for n in model.graph.node
               if any(hint in n.op_type for hint in QUANT_HINTS))


def weights(model) -> list[tuple[str, str, tuple[int, ...], int, int]]:
    """重み（initializer）の一覧。(名前, 型, 形状, 要素数, バイト数)。"""
    out = []
    for init in model.graph.initializer:
        arr = numpy_helper.to_array(init)
        out.append((init.name, str(arr.dtype), tuple(arr.shape),
                    int(arr.size), int(arr.nbytes)))
    return out


def describe(path: Path) -> None:
    model = onnx.load(str(path))
    ws = weights(model)
    total_bytes = sum(w[4] for w in ws)
    total_elems = sum(w[3] for w in ws)

    print(f"=== {path.name} ===")
    print(f"ファイルサイズ : {path.stat().st_size / MB:.2f} MB")
    print(f"IR バージョン  : {model.ir_version}")
    print("opset          : "
          + " / ".join(f"{o.domain or '既定'}={o.version}" for o in model.opset_import))
    print(f"グラフ名       : {model.graph.name}")
    for i in model.graph.input:
        print(f"入力           : {i.name} {dtype_text(i)} {shape_text(i)}")
    for o in model.graph.output:
        print(f"出力           : {o.name} {dtype_text(o)} {shape_text(o)}")
    print(f"ノード数       : {len(model.graph.node)}")
    print("演算子の内訳   : "
          + ", ".join(f"{k} x{v}" for k, v in op_counts(model).items()))
    print(f"量子化のノード : {quant_nodes(model)} 個")
    print(f"重み           : {len(ws)} 個 / 合計 {total_bytes / MB:.2f} MB / "
          f"要素数 {total_elems:,}")
    for name, dtype, shape, _elems, nbytes in ws:
        print(f"  {name}: {dtype} {shape} {nbytes / MB:.2f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="ONNX ファイル（省略すると fp32 の分類器）")
    args = ap.parse_args()

    paths = [Path(p) for p in args.paths] or [DEFAULT_MODEL]
    for i, raw in enumerate(paths):
        path = raw if raw.is_absolute() else SANDBOX / raw
        if not path.exists():
            print(f"{path} がありません。"
                  "先に `python tools/make_edge_model.py` を実行してください。")
            sys.exit(1)
        if i:
            print()
        describe(path)


if __name__ == "__main__":
    main()
