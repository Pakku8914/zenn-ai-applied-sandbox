"""p 値の定義を、答えが手計算でも出せるコイン投げで確かめる。

使い方:
    docker compose exec lab python src/session10/pvalue_coin.py
"""

from __future__ import annotations

from math import comb

from scipy import stats

TRIALS = 10  # 投げた回数
HEADS = 8  # 表が出た回数


def main() -> None:
    # 帰無仮説: このコインは歪んでいない（表の出る確率はちょうど 0.5）
    total = 2**TRIALS
    ways = sum(comb(TRIALS, k) for k in range(HEADS, TRIALS + 1))
    print(f"10 回投げたときの出方の総数: {total} 通り")
    print(f"表が 8 回以上になる出方: {ways} 通り")
    print(f"手計算の確率（{ways}/{total}）: {ways / total:.4f}")

    # scipy で同じ値を出す。sf(k-1) は「k 回以上になる確率」
    print(f"表が 8 回以上（stats.binom.sf）: {stats.binom.sf(HEADS - 1, TRIALS, 0.5):.4f}")
    print(f"表が 9 回以上: {stats.binom.sf(8, TRIALS, 0.5):.4f}")
    print(f"表が 10 回: {stats.binom.pmf(10, TRIALS, 0.5):.4f}")

    # 「表に偏っている」だけでなく「裏に偏っている」も同じくらい極端とみなすのが両側検定
    two_sided = stats.binomtest(HEADS, TRIALS, 0.5, alternative="two-sided")
    greater = stats.binomtest(HEADS, TRIALS, 0.5, alternative="greater")
    print(f"両側検定の p 値: {two_sided.pvalue:.4f}")
    print(f"片側検定（表に偏る）の p 値: {greater.pvalue:.4f}")

    print()
    print("この 0.1094 は「コインが歪んでいない確率」ではありません。")
    print("「歪んでいないと仮定したとき、8 回表と同じかそれ以上に偏る確率」です。")


if __name__ == "__main__":
    main()
