#!/usr/bin/env python3
"""変換と実行の失敗をわざと起こして切り分ける（セッション12）。

  python src/session12/failure_lab.py

大事なのは**どこで落ちたか**である。

  ・変換の入口（onnx.checker）で落ちる -> モデルの表現そのものが不正
  ・実行時（session.run）で落ちる       -> ファイルは正しいが、呼び方が違う

この2つを混ぜると、直すべき場所を延々と間違える。実行時の失敗は
「変換をやり直す」では絶対に直らない。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.edge import make_session  # noqa: E402

LAB_DIR = SANDBOX / "models" / "onnx" / "lab"
SEED = 20260815
INPUT_DIM = 384
N_CLASSES = 6


@dataclass(frozen=True)
class Case:
    label: str
    where: str            # "変換の入口" か "実行時"
    expect_fail: bool     # 落ちることを期待しているか
    raised: str | None    # 実際に出た例外の型名（落ちなければ None）
    hint: str             # 対処

    @property
    def as_expected(self) -> bool:
        return (self.raised is not None) == self.expect_fail

    @property
    def result_text(self) -> str:
        return f"落ちた（{self.raised}）" if self.raised else "通った"


def make_proto(batch: int | str = 1, op_type: str = "MatMul",
               in_name: str = "input") -> onnx.ModelProto:
    """失敗の再現用に、1層だけの小さな分類器を作る（数十KB）。

    batch に文字列（"batch" など）を渡すと、その次元は動的になる。
    op_type に ONNX に無い名前を渡すと、変換の入口で落ちるモデルになる。
    """
    rng = np.random.default_rng(SEED)
    w = numpy_helper.from_array(
        rng.normal(scale=0.05, size=(INPUT_DIM, N_CLASSES)).astype(np.float32), "w")
    nodes = [helper.make_node(op_type, [in_name, "w"], ["logits"]),
             helper.make_node("Softmax", ["logits"], ["probs"], axis=-1)]
    graph = helper.make_graph(
        nodes, "tiny_classifier",
        inputs=[helper.make_tensor_value_info(in_name, TensorProto.FLOAT,
                                              [batch, INPUT_DIM])],
        outputs=[helper.make_tensor_value_info("probs", TensorProto.FLOAT,
                                              [batch, N_CLASSES])],
        initializer=[w])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 20)])
    model.ir_version = 10       # onnxruntime 1.28 が読める IR バージョンに固定する
    return model


def save(proto: onnx.ModelProto, name: str) -> Path:
    LAB_DIR.mkdir(parents=True, exist_ok=True)
    path = LAB_DIR / f"{name}.onnx"
    onnx.save(proto, path)
    return path


def attempt(label: str, where: str, expect_fail: bool,
            fn: Callable[[], object], hint: str) -> Case:
    """1件試して、例外の型名だけを記録する。メッセージは版で変わるので保存しない。"""
    raised = None
    try:
        fn()
    except Exception as exc:      # noqa: BLE001  どんな失敗が出るかを見せるのが目的
        raised = type(exc).__name__
    return Case(label, where, expect_fail, raised, hint)


def inputs(batch: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    return rng.normal(size=(batch, INPUT_DIM)).astype(np.float32)


def run_cases() -> list[Case]:
    cases: list[Case] = []

    # [1] 未対応の演算子：学習フレームワーク固有の層が ONNX の標準演算子に無い
    broken = make_proto(op_type="MyCustomAttention")
    cases.append(attempt(
        "未対応の演算子（ONNX に無い層が残っている）", "変換の入口", True,
        lambda: onnx.checker.check_model(broken),
        "標準の演算子に置き換える／opset を上げる／その部分だけ自分で実装する"))

    fixed = save(make_proto(batch=1), "tiny_fixed")
    dynamic = save(make_proto(batch="batch"), "tiny_dynamic")
    x1, x4 = inputs(1), inputs(4)
    sess_fixed = make_session(fixed, 1)
    sess_dynamic = make_session(dynamic, 1)

    # [2] 形状の不一致：バッチ1で固定したモデルに4件まとめて渡す
    cases.append(attempt(
        "形状の不一致（バッチ1固定のモデルに4件渡す）", "実行時", True,
        lambda: sess_fixed.run(None, {"input": x4}),
        "バッチ次元を動的にする／1件ずつ回す（端末では1件ずつが普通）"))

    # [3] [2] の対処：バッチ次元だけ動的にすると、同じ入力が通る
    cases.append(attempt(
        "同じ入力を、バッチ次元が動的なモデルに渡す", "実行時", False,
        lambda: sess_dynamic.run(None, {"input": x4}),
        "「変換できた」と「使いたい形で動く」は別。形状は契約である"))

    # [4] 入力名の不一致：feeds のキーはモデル側の入力名と一致していないといけない
    cases.append(attempt(
        '入力の名前が違う（feeds のキーを "x" にした）', "実行時", True,
        lambda: sess_fixed.run(None, {"x": x1}),
        "session.get_inputs()[0].name で実際の名前を確認して合わせる"))

    # [5] 入力の型の不一致：numpy の既定は float64、モデルは float32
    cases.append(attempt(
        "入力の型が違う（float64 のまま渡した）", "実行時", True,
        lambda: sess_fixed.run(None, {"input": x1.astype(np.float64)}),
        "astype(np.float32) を前処理に必ず入れる"))

    return cases


def main() -> None:
    cases = run_cases()
    print("=== 変換と実行の失敗を切り分ける ===")
    for i, c in enumerate(cases, start=1):
        print(f"\n[{i}] {c.label}")
        print(f"    結果   : {c.result_text}")
        print(f"    どこで : {c.where}")
        print(f"    対処   : {c.hint}")

    ok = sum(1 for c in cases if c.as_expected)
    print(f"\n想定どおりの結果: {ok}/{len(cases)} 件")
    print("例外の型名は onnxruntime のバージョンで変わることがあります。"
          "見るべきは「変換の入口か、実行時か」です。")
    if ok != len(cases):
        sys.exit(1)


if __name__ == "__main__":
    main()
