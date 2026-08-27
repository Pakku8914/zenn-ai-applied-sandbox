#!/usr/bin/env python3
"""セッション1で動かした「経費レポート作成」を、ワークフローとして書き直す。

エージェント版（scenarios/expense_report.json）は LLM を4回呼んで同じ成果物を作った。
こちらは LLM 呼び出し 0 回である。差が出るのは速さとコストだけではない。
**集計と注記の規則を人間が明示的に書く**ことになるのが最大の違いである。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import DATA, write_file  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402

# 出力の並びを固定する（辞書の順に任せると月ごとに並びが変わる）
CATEGORY_ORDER = ("交通費", "接待交際費", "備品", "出張旅費")


def load_expenses() -> list[dict]:
    path = DATA / "expenses.jsonl"
    if not path.exists():
        raise SystemExit(
            "data/expenses.jsonl がありません。python tools/make_data.py を実行してください。")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def totals(rows: list[dict]) -> dict[str, int]:
    """区分ごとに合計する。

    却下済み（status=rejected）も合計に含める。「含める／含めない」は業務の判断であり、
    ワークフローでは**書かないと動かない**。エージェント版はこれを暗黙に決めていた。
    """
    result: dict[str, int] = {}
    for row in rows:
        result[row["category"]] = result.get(row["category"], 0) + row["amount"]
    return result


def violations(rows: list[dict]) -> list[str]:
    """規程違反として注記する行を選ぶ。却下済みは既に処理済みなので除く。"""
    return [f"{row['expense_id']}: {row['note']}" for row in rows
            if row["note"] and row["status"] != "rejected"]


def build_report(rows: list[dict], clock: FixedClock | None = None) -> str:
    now = (clock or FixedClock()).now()
    sums = totals(rows)
    lines = [f"# {now.year}年{now.month}月 経費レポート", ""]
    for category in CATEGORY_ORDER:
        if category in sums:
            lines.append(f"- {category}: {sums[category]:,}円")
    for category in sorted(sums):  # 想定していない区分が来ても落とさない
        if category not in CATEGORY_ORDER:
            lines.append(f"- {category}: {sums[category]:,}円")
    lines.append(f"- 合計: {sum(sums.values()):,}円")
    lines.append("")
    lines.append("## 規程違反の注記")
    notes = violations(rows)
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- なし")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = load_expenses()
    report = build_report(rows)
    print(report)
    write_file("report_workflow.md", report)
    print("workspace/report_workflow.md に書き出しました。")
    print(f"LLM 呼び出し: 0 回 / 集計対象: {len(rows)} 件")
    print("※ 却下済み（EXP-0005）も区分合計に含めています。この判断はコードに書いてあります。")


if __name__ == "__main__":
    main()
