#!/usr/bin/env python3
"""重みを int8 にして C の配列として書き出し、バイト数を数える（セッション14）。

本書が扱うのは **Python で C のソースを生成するところまで**である。生成した配列を
使って推論するループの実装・レジスタ制御・RTOS は姉妹教材
『手を動かして学ぶ 組み込みC言語実践入門』の領域なので、ここでは踏み込まない。

この章で数える対象は3つあり、**混ぜてはいけない**。

  ① 要素数                   : 配列の長さ
  ② Flash に焼かれるバイト数 : 要素数 × 1要素のバイト数（int8 なら 1）
  ③ C のソースのバイト数     : テキストの大きさ。**Flash の消費量ではない**

    python src/session14/c_array.py
    python src/session14/c_array.py --elements 1024
    python src/session14/c_array.py --out models/c/model_w1.c
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcu_budget import DEVICE_E, KB, MODEL_C12, MODEL_K  # noqa: E402

# ③ 前提値：説明用の小さな重み（8 要素）。乱数を使わないので誰の環境でも同じ値になる。
DEMO_FP32 = np.array([0.10, -0.25, 0.40, -0.05, 0.15, -0.35, 0.22, 0.31],
                     dtype=np.float32)

HEADER_COMMENT = "// 自動生成: src/session14/c_array.py"


def quantize_symmetric(x: np.ndarray) -> tuple[np.ndarray, float]:
    """対称量子化。スケール1つで int8 に落とす（セッション12と同じ考え方）。

    戻り値は (int8 の配列, スケール)。**スケールを一緒に配らないと元の値に戻せない。**
    """
    amax = float(np.max(np.abs(x)))
    scale = amax / 127.0 if amax > 0 else 1.0
    q = np.clip(np.rint(x / scale), -127, 127).astype(np.int8)
    return q, scale


def emit_c_array(name: str, data: np.ndarray, scale: float, per_line: int = 16) -> str:
    """C のソースを組み立てる。**手で編集しないこと**を示すコメントを先頭に置く。"""
    flat = np.asarray(data).reshape(-1)
    n = int(flat.size)
    lines = [
        HEADER_COMMENT,
        "#include <stdint.h>",
        "",
        f"const uint32_t {name}_len = {n};",
        f"const float {name}_scale = {scale:.8f}f;",
        f"const int8_t {name}[{n}] = {{",
    ]
    for i in range(0, n, per_line):
        chunk = ", ".join(str(int(v)) for v in flat[i:i + per_line])
        lines.append(f"  {chunk},")
    lines.append("};")
    return "\n".join(lines) + "\n"


def flash_bytes(data: np.ndarray, bytes_per_element: int = 1) -> int:
    """② Flash に焼かれるバイト数。**要素数 × 1要素のバイト数だけ**である。"""
    return int(np.asarray(data).size) * bytes_per_element


def source_bytes(text: str) -> int:
    """③ C のソースのバイト数。判定には使わない（テキストは焼かれない）。"""
    return len(text.encode("utf-8"))


def source_bounds(n_elements: int) -> tuple[int, int]:
    """ソースのバイト数が満たす下限と上限（②決定的）。

    1要素は最短1文字（`0`）・最長4文字（`-128`）、区切りは `, ` の2文字。
    ヘッダとフッタは要素数によらずおおむね一定（200 バイト強）なので余裕をみて 256。
    """
    return 3 * n_elements, 6 * n_elements + 256


def ram_copy_kb(n_elements: int, const_qualified: bool, bytes_per_element: int = 1) -> float:
    """`const` を付けなければ、同じ大きさのコピーが起動時に RAM へ載る。"""
    return 0.0 if const_qualified else n_elements * bytes_per_element / KB


def print_quantize() -> tuple[np.ndarray, float]:
    q, scale = quantize_symmetric(DEMO_FP32)
    amax = float(np.max(np.abs(DEMO_FP32)))
    print("=== 1) fp32 を int8 に落とす（②決定的な計算）===")
    print("入力（fp32・8 要素）: " + ", ".join(f"{v:.2f}" for v in DEMO_FP32))
    print(f"最大の絶対値: {amax:.6f} / スケール（最大の絶対値 ÷ 127）: {scale:.8f}")
    print("量子化後（int8）: " + ", ".join(str(int(v)) for v in q))
    return q, scale


def print_source(src: str) -> None:
    print("\n=== 2) C の配列として書き出す ===")
    print(src, end="")


def print_bytes(q: np.ndarray, src: str) -> None:
    fb, sb = flash_bytes(q), source_bytes(src)
    print("\n=== 3) 何バイトになるか（②決定的な計算）===")
    print("| 数えるもの | 値 |")
    print("| :--- | --: |")
    print(f"| 要素数 | {int(q.size):,} |")
    print(f"| Flash に置かれるバイト数（int8・1要素1バイト） | {fb:,} バイト |")
    print(f"| C のソースのバイト数 | {sb:,} バイト |")
    print(f"| ソース ÷ Flash | {sb / fb:.1f} 倍 |")
    print("-> **ソースの大きさは Flash の消費量ではない。** 焼かれるのは配列の中身だけである。")


def print_const() -> None:
    w = MODEL_K.weights_kb()
    arena = MODEL_K.arena_peak_kb()
    limit = DEVICE_E.arena_limit_kb
    print("\n=== 4) const を忘れるとどうなるか（③前提値：端末E）===")
    print("| 書き方 | Flash | RAM（重みのコピー） | アリーナ合計 | 上限比 |")
    print("| :--- | --: | --: | --: | --: |")
    for label, is_const in (("const int8_t（正）", True), ("int8_t（const なし）", False)):
        copy_kb = ram_copy_kb(MODEL_K.params, is_const)
        total = arena + copy_kb
        print(f"| {label} | {w:.2f} KB | {copy_kb:.2f} KB | {total:.2f} KB | "
              f"{total / limit:.1%} |")
    print(f"-> モデルK は const を忘れても動くが、RAM の使用率が {arena / limit:.1%} -> "
          f"{(arena + w) / limit:.1%} に跳ねる。")
    c12 = MODEL_C12.weights_kb()
    print(f"-> セッション12の分類器（{MODEL_C12.params:,} 要素）なら RAM に {c12:.2f} KB "
          "のコピーが載る。")
    print(f"   端末E のアリーナ上限 {limit:.2f} KB の {c12 / limit:.1f} 倍で、"
          "**起動した瞬間に落ちる。**")


def demo_int8(n: int) -> np.ndarray:
    """③ 前提値：要素数を変えて数えるための決定的なパターン（乱数を使わない）。"""
    i = np.arange(n, dtype=np.int32)
    return ((i * 37) % 255 - 127).astype(np.int8)


def print_elements(n: int) -> None:
    data = demo_int8(n)
    src = emit_c_array("model_big", data, 1.0 / 127.0)
    fb, sb = flash_bytes(data), source_bytes(src)
    low, high = source_bounds(n)
    print(f"\n=== 5) 要素数を変えて数える（--elements {n:,}）===")
    print("| 要素数 | Flash | C のソース | ソース ÷ Flash |")
    print("| --: | --: | --: | --: |")
    print(f"| {n:,} | {fb:,} バイト | {sb:,} バイト | {sb / fb:.1f} 倍 |")
    print(f"-> 下限と上限の式: 3 × N = {low:,} < ソース < 6 × N + 256 = {high:,}")
    print("-> 要素数が増えるとヘッダの寄与が薄まり、比は小さくなる。"
          "**26 倍という比は小さい配列に特有の見かけである。**")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="重みを C の配列に落としてバイト数を数える")
    ap.add_argument("--elements", type=int, default=0,
                    help="この要素数でも数える（例: 1024）")
    ap.add_argument("--out", type=Path, default=None,
                    help="生成した C のソースを書き出す先（生成物なので models/c/ 以下に置く）")
    args = ap.parse_args(argv)

    q, scale = print_quantize()
    src = emit_c_array("model_w1", q, scale)
    print_source(src)
    print_bytes(q, src)
    print_const()
    if args.elements > 0:
        print_elements(args.elements)
    if args.out is not None:
        out = args.out if args.out.is_absolute() else SANDBOX / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(src, encoding="utf-8")
        print(f"\n書き出しました: {out}（{source_bytes(src):,} バイト）")


if __name__ == "__main__":
    main()
