#!/usr/bin/env python3
"""エッジ実験用の ONNX モデルを決定的に作る（セッション12・13）。

torch を入れずに ONNX を直接組み立てる。理由は2つある。

1. **エッジ側の環境に学習フレームワークを置かない**のが実務の基本形。
   端末に必要なのは推論ランタイムだけで、torch は数GBある（本書のイメージは
   これを避けて 300MB 台に収まっている）。
2 .固定シードで生成するので、誰の環境でも同じサイズ・同じ出力になる。

作るのは「問い合わせの特徴量 → 6区分」の分類器を想定した多層パーセプトロン。
実際の学習済みモデルではないが、量子化のサイズ・速度・出力差の測定には十分。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parent.parent
ONNX_DIR = SANDBOX / "models" / "onnx"
SEED = 20260815
INPUT_DIM = 384  # 埋め込みの次元（book1 の e5-small と同じにしてある）
N_CLASSES = 6


def build(hidden: int, name: str) -> Path:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(SEED)

    def weight(shape, tag):
        # Xavier 相当のスケールで作る（値が飽和しないように）
        w = rng.normal(scale=(2.0 / sum(shape)) ** 0.5, size=shape).astype(np.float32)
        return numpy_helper.from_array(w, tag)

    w1, w2, w3 = weight((INPUT_DIM, hidden), "w1"), weight((hidden, hidden), "w2"), \
        weight((hidden, N_CLASSES), "w3")
    b1 = numpy_helper.from_array(np.zeros(hidden, dtype=np.float32), "b1")
    b2 = numpy_helper.from_array(np.zeros(hidden, dtype=np.float32), "b2")
    b3 = numpy_helper.from_array(np.zeros(N_CLASSES, dtype=np.float32), "b3")

    nodes = [
        helper.make_node("MatMul", ["input", "w1"], ["h1"]),
        helper.make_node("Add", ["h1", "b1"], ["h1b"]),
        helper.make_node("Relu", ["h1b"], ["a1"]),
        helper.make_node("MatMul", ["a1", "w2"], ["h2"]),
        helper.make_node("Add", ["h2", "b2"], ["h2b"]),
        helper.make_node("Relu", ["h2b"], ["a2"]),
        helper.make_node("MatMul", ["a2", "w3"], ["h3"]),
        helper.make_node("Add", ["h3", "b3"], ["logits"]),
        helper.make_node("Softmax", ["logits"], ["probs"], axis=-1),
    ]
    graph = helper.make_graph(
        nodes, "helpdesk_classifier",
        # 【要点】バッチ次元を固定する。端末では基本的にバッチ1で、
        # 形状を固定すると最適化が効きやすい（セッション12で扱う）
        inputs=[helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, INPUT_DIM])],
        outputs=[helper.make_tensor_value_info("probs", TensorProto.FLOAT, [1, N_CLASSES])],
        initializer=[w1, b1, w2, b2, w3, b3],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 20)])
    model.ir_version = 10
    onnx.checker.check_model(model)

    ONNX_DIR.mkdir(parents=True, exist_ok=True)
    out = ONNX_DIR / f"{name}.onnx"
    onnx.save(model, out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hidden", type=int, default=4096,
                    help="隠れ層の幅。小さすぎるとレイテンシがサブミリ秒になり測定ノイズに埋もれる")
    ap.add_argument("--name", default="classifier_fp32")
    args = ap.parse_args()

    path = build(args.hidden, args.name)
    size_mb = path.stat().st_size / 1024 / 1024
    params = INPUT_DIM * args.hidden + args.hidden * args.hidden + args.hidden * N_CLASSES
    print(f"作成: {path.relative_to(SANDBOX)}")
    print(f"隠れ層     : {args.hidden}")
    print(f"パラメータ : {params / 1e6:.2f}M")
    print(f"サイズ     : {size_mb:.2f} MB（fp32 なので パラメータ × 4 バイト）")
    if size_mb < 1:
        print("警告: 小さすぎて量子化の効果が測りにくいです。--hidden を増やしてください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
