#!/usr/bin/env python3
"""対応演算子の突き合わせ（セッション14）。

**メモリが足りていても、演算子が未対応なら載らない。** 関門は2つある。

:::注意:::
`SUPPORTED` と `ALTERNATIVES` は **③ 前提値**である。特定のランタイムの実際の対応状況を
主張するものではない。実務では、自分が使うランタイムの公式ドキュメントの対応表を
ここに書き写して使う（書き写した日付も残す）。「教材に 13 個と書いてあった」を
根拠にしてはいけない。

    python src/session14/op_support.py
"""

from __future__ import annotations

from dataclasses import dataclass

# ③ 前提値：小さなランタイムが持っていそうなカーネルの一例（13 個）
SUPPORTED: frozenset[str] = frozenset({
    "Conv", "DepthwiseConv2D", "FullyConnected", "MaxPool2D", "AveragePool2D",
    "Relu", "Relu6", "Softmax", "Reshape", "Add", "Mul", "Quantize", "Dequantize",
})

# ③ 前提値：未対応だったときの対処。3段階（置き換えれば済む／学習し直し／不可）に分かれる。
ALTERNATIVES: dict[str, str] = {
    "MatMul": "FullyConnected に置き換える（形を固定する）",
    "Gelu": "Relu に置き換えて学習し直す",
    "LayerNormalization": "学習後に畳み込みへ畳み込む（fold する）",
    "Resize": "前処理で入力サイズを固定して取り除く",
    "Attention": "置き換えられない。タスクを変える",
}

DEFAULT_ADVICE = "対応表に無い。ランタイムの実装状況を自分で確認する"

# ③ 前提値：モデルのグラフ（演算子の並び）。実在のモデルの厳密な構成ではなく、
#            「どこで止まるか」を見るための見本である。
GRAPHS: dict[str, tuple[str, ...]] = {
    "K キーワード検出": (
        "Quantize", "Conv", "Relu", "DepthwiseConv2D", "Relu", "MaxPool2D",
        "Reshape", "FullyConnected", "Softmax", "Dequantize",
    ),
    "C12 セッション12の分類器": (
        "Quantize", "MatMul", "Add", "Relu", "MatMul", "Add", "Relu",
        "MatMul", "Add", "Softmax", "Dequantize",
    ),
    "小さな言語モデル": (
        "Quantize", "Embedding", "LayerNormalization", "MatMul", "Attention",
        "Gelu", "MatMul", "Softmax",
    ),
}


@dataclass(frozen=True)
class OpReport:
    name: str
    ops: tuple[str, ...]
    unsupported: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.unsupported

    def text(self) -> str:
        return "そのまま載せられる" if self.ok else "置き換えが必要"


def check_ops(name: str, ops: tuple[str, ...],
              supported: frozenset[str] | set[str] = SUPPORTED) -> OpReport:
    """未対応の演算子を列挙する。**個数ではなく中身で判断する。**"""
    missing = tuple(sorted({op for op in ops if op not in supported}))
    return OpReport(name, tuple(ops), missing)


def advice(op: str) -> str:
    return ALTERNATIVES.get(op, DEFAULT_ADVICE)


def main() -> None:
    print("=== 対応演算子の突き合わせ（③前提値：あなたのランタイムの対応表を書き写す）===")
    print(f"対応表に載っている演算子: {len(SUPPORTED)} 個")
    print()
    print("| モデル | 演算子の数 | 未対応 | 判定 |")
    print("| :--- | --: | :--- | :--- |")
    missing: set[str] = set()
    for name, ops in GRAPHS.items():
        r = check_ops(name, ops)
        missing |= set(r.unsupported)
        print(f"| {name} | {len(r.ops)} | {', '.join(r.unsupported) or 'なし'} | {r.text()} |")

    print("\n=== 未対応の演算子への対処 ===")
    print("| 演算子 | 対処 |")
    print("| :--- | :--- |")
    for op in sorted(missing):
        print(f"| {op} | {advice(op)} |")
    print("-> 演算子が1つ未対応なだけで、**変換は最後の一歩で止まる。**")
    print("-> **載る／載らないは、メモリだけでは決まらない。** 演算子の対応も同じ関門である。")


if __name__ == "__main__":
    main()
