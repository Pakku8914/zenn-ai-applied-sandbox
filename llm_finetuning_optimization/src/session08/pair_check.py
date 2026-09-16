#!/usr/bin/env python3
"""選好ペアの「差の軸」を数える（セッション8・モデルを読まない）。

DPO が学ぶのは **chosen と rejected の差** である。差が2つ以上あると、
モデルはどちらの差を好まれたのか区別できない。学習を回す前に、ペアを機械的に
検査して「差が1軸に絞れているか」を確かめるのがこのモジュールの役目。

  python src/session08/pair_check.py        # 同梱の選好データ 200 件を集計する
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.evaluate import FORMAT_RE  # noqa: E402

# 断定を避ける表現（あると「自信の無さ」という別の軸が混ざる）
HEDGES = ("くらい", "ぐらい", "たぶん", "多分", "かも", "と思います", "みたい", "はず", "だいたい")

# 【担当】に入りうる部署名（事実が変わっていないかを見るため）
OWNERS = ("経理部", "総務部", "情報システム部", "情報セキュリティ室")

AXIS_LABELS = {
    "format": "3行の定型を守るか",
    "hedge": "断定を避けるぼかし表現があるか",
    "length": "文字数が大きく違うか",
    "owner": "担当部署が変わっているか",
}


def is_format(text: str) -> bool:
    """【区分】【担当】【期限】の3行になっているか（評価と同じ正規表現を使う）。"""
    return bool(FORMAT_RE.match(text.strip()))


def has_hedge(text: str) -> bool:
    return any(hedge in text for hedge in HEDGES)


def owner_of(text: str) -> str:
    for owner in OWNERS:
        if owner in text:
            return owner
    return ""


def diff_axes(chosen: str, rejected: str, length_ratio: float = 1.5) -> list[str]:
    """chosen と rejected が「どの軸で」違うかを列挙する。

    返り値の要素数が1なら良いペア（差が1軸）、2以上なら何を学ぶかが曖昧なペア。
    """
    axes: list[str] = []
    if is_format(chosen) != is_format(rejected):
        axes.append("format")
    if has_hedge(chosen) != has_hedge(rejected):
        axes.append("hedge")
    longer, shorter = max(len(chosen), len(rejected)), min(len(chosen), len(rejected))
    if longer / max(shorter, 1) >= length_ratio:
        axes.append("length")
    if owner_of(chosen) != owner_of(rejected):
        axes.append("owner")
    return axes


def axis_counts(rows: list[dict], length_ratio: float = 1.5) -> Counter:
    """軸の組み合わせごとにペア数を数える。"""
    return Counter(
        tuple(diff_axes(row["chosen"], row["rejected"], length_ratio)) for row in rows
    )


def length_gaps(rows: list[dict]) -> list[int]:
    """rejected の文字数 − chosen の文字数。長さの交絡を見るために使う。"""
    return [len(row["rejected"]) - len(row["chosen"]) for row in rows]


def main() -> None:
    from ftkit.data import load_preference

    rows = load_preference()
    print(f"選好ペア {len(rows)} 件を検査します（差が1軸に絞れているかを見る）\n")
    for axes, count in axis_counts(rows).most_common():
        labels = " / ".join(AXIS_LABELS[a] for a in axes) if axes else "差なし"
        print(f"  {count:>4} 件  軸 {len(axes)} 個  {list(axes)}  … {labels}")

    gaps = length_gaps(rows)
    chosen_avg = sum(len(r["chosen"]) for r in rows) / len(rows)
    rejected_avg = sum(len(r["rejected"]) for r in rows) / len(rows)
    print(f"\n  平均文字数: chosen {chosen_avg:.1f} / rejected {rejected_avg:.1f}")
    print(f"  文字数の差（rejected − chosen）: {sorted(set(gaps))}")
    print("  → 差の値が1種類しかない場合、長さは形式と完全に交絡している")


if __name__ == "__main__":
    main()
