#!/usr/bin/env python3
"""ツールの宣言から、並列にしてよい塊を決める（S03 の並列 × S04 の宣言）。

S03 では「読み取り専用なら並列でよい」と決めた。S04 では `tags` / `idempotent` /
`requires_approval` をツール側の宣言として持たせた。この2つを繋ぐと、
**呼び出しの列を見て並列と直列に切り分ける**という判断がコードになる。

並列にしてよい条件（すべて満たすときだけ）:
  1. レジストリに登録されている（未知のツールは何も分からないので直列）
  2. `tags` に "read" を含む（副作用がない）
  3. `idempotent` が True（同じ呼び出しを繰り返しても結果が同じ）
  4. `requires_approval` が False（人間の判断が要るものを勝手にまとめない）

そして「並列」と言えるのは2件以上のときだけである。1件を並列と呼ぶと、
軌跡を読む人が「並列にしたのに速くならない」と誤解する。
"""

from __future__ import annotations


def parallel_safe(registry, call) -> bool:
    """1件の呼び出しを並列の対象にしてよいか。判断材料はツールの宣言だけ。"""
    tool = registry.get(call.name)
    return (tool is not None
            and "read" in tool.tags
            and tool.idempotent
            and not tool.requires_approval)


def _flush(group: list) -> list[tuple[str, list]]:
    if not group:
        return []
    if len(group) == 1:
        return [("serial", list(group))]
    return [("parallel", list(group))]


def plan_batches(registry, calls: list) -> list[tuple[str, list]]:
    """呼び出しの列を、実行の単位（"parallel" / "serial"）に切り分ける。

    連続する安全な読み取りだけをまとめる。**並び替えはしない**のが要点である。
    順序を変えると軌跡が実行ごとに変わり、再現しないテストになってしまう。
    """
    batches: list[tuple[str, list]] = []
    group: list = []
    for call in calls:
        if parallel_safe(registry, call):
            group.append(call)
            continue
        batches += _flush(group)
        group = []
        batches.append(("serial", [call]))
    return batches + _flush(group)


def render_batches(batches: list[tuple[str, list]]) -> str:
    """人が読める形にする（軌跡の `usage["batch"]` と対応させて読む）。"""
    return " → ".join(f"[{mode}] {', '.join(call.name for call in group)}"
                      for mode, group in batches)


def main() -> None:
    from _paths import setup

    setup()
    from agentkit.biztools import build_registry
    from agentkit.models import ToolCall

    registry = build_registry()

    def calls(*names: str) -> list:
        return [ToolCall(f"c{i}", name, {}) for i, name in enumerate(names)]

    samples = [
        ("読み取り3本", calls("get_policy", "list_expenses", "search_docs")),
        ("読み取り2本＋書き込み", calls("get_policy", "list_expenses", "write_file")),
        ("書き込みが真ん中に挟まる", calls("get_policy", "write_file", "list_expenses")),
        ("承認が必要な送信を含む", calls("search_docs", "send_message")),
        ("未登録のツール", calls("no_such_tool")),
    ]
    print("=== 呼び出しの列を実行の単位に切り分ける ===")
    for label, group in samples:
        print(f"{label}: {render_batches(plan_batches(registry, group))}")


if __name__ == "__main__":
    main()
