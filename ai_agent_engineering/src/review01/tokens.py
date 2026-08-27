#!/usr/bin/env python3
"""ツール結果の大きさが、会話履歴にどう積み上がるかを計算する。

S03 で「入力トークンはステップごとに増える（履歴が毎回全部送られる）」ことを見た。
S04 で「ツール結果の大きさは道具側の設計で決まる」ことを見た。この2つを掛けると、
**1手あたりの結果を小さくすると効果が手数の分だけ効いてくる**という関係になる。

トークン数は決定的な近似値（文字数 ÷ 3）である。実 API の課金額ではないので、
絶対値ではなく比較に使う（本書では「近似トークン数（比較用）」と呼ぶ）。
"""

from __future__ import annotations


def approx_tokens(text: str) -> int:
    """近似トークン数（比較用）＝文字数 ÷ 3。"""
    return len(text) // 3


def history_tokens(result_chars: list[int], *, task_chars: int = 30) -> list[int]:
    """ステップごとの近似入力トークンを返す。

    ツール結果は、返ってきた次のステップ以降**ずっと**送られ続ける。
    そのため i 番目のステップの入力は「タスク文＋それまでの結果の合計」になる。
    返る要素数は `len(result_chars) + 1`（最後の1手は報告のためのステップ）。
    """
    if task_chars < 0 or any(chars < 0 for chars in result_chars):
        raise ValueError("文字数は0以上で指定してください。")
    tokens: list[int] = []
    total = task_chars
    for chars in [0, *result_chars]:
        total += chars
        tokens.append(total // 3)
    return tokens


def total_tokens(result_chars: list[int], *, task_chars: int = 30) -> int:
    """タスク1件で送られる入力の近似トークンの合計。"""
    return sum(history_tokens(result_chars, task_chars=task_chars))


def main() -> None:
    # S04 の実測（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13）：
    # 同じ問いに対する返し方で 1,038 文字と 102 文字の差が出ていた
    print("=== ツール結果の大きさが会話履歴に効く（3手＋報告1手・近似トークン） ===")
    totals = []
    for chars in (1038, 102):
        tokens = history_tokens([chars] * 3)
        totals.append(sum(tokens))
        print(f"結果 {chars:>4} 文字 × 3手: {tokens} 合計 {sum(tokens)}")
    print(f"同じ手数・同じ停止理由でも、入力の近似トークンは "
          f"{totals[0] / totals[1]:.1f} 倍違う")


if __name__ == "__main__":
    main()
