#!/usr/bin/env python3
"""前方一致（プロンプトキャッシュ）が効く条件を測る（セッション6）。

推論サーバは要らない。前方一致で共有できる量は**文字列だけで決まる**ので、
環境が違っても同じ数字になる（レイテンシと違ってぶれない）。

    python src/session06/prefix_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cache import PrefixCache  # noqa: E402
from tools.prompts import (  # noqa: E402
    QUESTIONS, SYSTEM_PREFIX, with_shared_prefix, with_unique_prefix,
)

# 全員ちがう社員から1件ずつ届く状況を作る（本番のリクエスト列に近い）
USERS: list[tuple[str, str]] = [
    ("田中", "総務部"),
    ("佐藤", "情報システム部"),
    ("鈴木", "物流部"),
    ("高橋", "経理部"),
    ("渡辺", "営業部"),
    ("伊藤", "人事部"),
]


def mean_shared_ratio(prompts: list[str]) -> float:
    """プロンプト集の平均前方一致率（先頭のうち何割が既出と共有できたか）。"""
    return PrefixCache().report(prompts)["mean_shared_ratio"]


def shared_prefix_chars(prompts: list[str]) -> int:
    """2件目以降が先頭で共有できた文字数の最小値。

    比率より読みやすい指標。「必ずこれだけは共有できる」量を表す。
    """
    cache = PrefixCache()
    shared: list[int] = []
    for i, prompt in enumerate(prompts):
        n = cache.common_prefix_len(prompt)
        if i:
            shared.append(n)
        cache.add(prompt)
    return min(shared) if shared else 0


def layout_bad(name: str, dept: str, question: str) -> str:
    """可変情報（氏名・部署）を先頭に置く。1文字目から違うので何も共有できない。"""
    return f"{name}（{dept}）さんからの質問です。\n" + SYSTEM_PREFIX + question


def layout_good(name: str, dept: str, question: str) -> str:
    """固定のシステムプロンプトを先頭に置き、可変情報は後ろに回す。"""
    return (SYSTEM_PREFIX
            + "質問者の情報:\n- 氏名: " + name
            + "\n- 部署: " + dept
            + "\n\n質問:\n" + question)


def build(layout) -> list[str]:
    """1人1件ずつ、指定した配置でプロンプトを組み立てる。"""
    return [layout(name, dept, q)
            for (name, dept), q in zip(USERS, QUESTIONS[:len(USERS)])]


def compare_layouts() -> dict[str, float]:
    bad, good = build(layout_bad), build(layout_good)
    return {
        "bad_chars": shared_prefix_chars(bad),
        "good_chars": shared_prefix_chars(good),
        "bad_ratio": mean_shared_ratio(bad),
        "good_ratio": mean_shared_ratio(good),
    }


def main() -> None:
    shared = mean_shared_ratio(with_shared_prefix())
    unique = mean_shared_ratio(with_unique_prefix())
    print("=== 前方一致率（tools/prompts.py の 20 件）===")
    print(f"共通のシステムプロンプトを先頭に置く: 平均 {shared:.3f}")
    print(f"先頭に一意なリクエストIDを付ける: 平均 {unique:.3f}")
    print(f"比: {shared / unique:.1f} 倍")
    print("※ 値は文字列だけで決まるので、環境が違っても同じ数字になります。")

    layouts = compare_layouts()
    print()
    print("=== プロンプトの配置を変える（6件・全員ちがう社員）===")
    print(f"ユーザー情報を先頭に置く: 共有できた先頭 {layouts['bad_chars']} 文字")
    print(f"ユーザー情報を後ろに回す: 共有できた先頭 {layouts['good_chars']} 文字")


if __name__ == "__main__":
    main()
