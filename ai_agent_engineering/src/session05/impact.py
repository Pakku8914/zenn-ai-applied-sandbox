#!/usr/bin/env python3
"""規程改定の影響を実データから計算し、レポートを組み立て、成果物を採点する。

セッション5の題材は「経費精算規程の改定案の影響調査」である。
台本（plans.py）が書くレポートの中身は、ここで data/expenses.jsonl から
決定的に計算した事実で作る。台本に数値を直接書かないのは、データが変わったときに
本文の数値と成果物が食い違うのを防ぐため。

    python src/session05/impact.py     # 計算した事実と満点のレポートを表示する
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# FixedClock と同じ基準日。datetime.now() は使わない（軌跡が再現しなくなる）
BASE_DATE = date(2026, 8, 15)

OLD_APPROVAL = 50_000   # 現行：1件5万円以上は事前承認が必要
NEW_APPROVAL = 10_000   # 改定案：1万円以上に引き下げる
OLD_DEADLINE_DAYS = 10  # 現行：支出日から10日以内に申請
NEW_DEADLINE_DAYS = 5   # 改定案：5日以内に短縮する

# 全方式で同じタスク文を使う（比較を成立させるため、ここだけを唯一の出典にする）
TASK = (
    "経費精算規程の改定案（事前承認の基準額を5万円から1万円へ、申請期限を10日から5日へ）が、"
    "いまの経費申請にどう影響するかを調べてください。"
    "申請の起票日から基準日 2026-08-15 までの経過日数を「処理までの日数」とみなします。"
    "現行規程の内容・金額基準の影響・申請期限の影響・対応方針を含む影響調査レポートを、"
    "作業領域に保存してください。"
)


def load_expenses() -> list[dict]:
    path = DATA / "expenses.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。`python tools/make_data.py` を実行してください。"
        )
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def elapsed_days(row: dict) -> int:
    """起票日から基準日までの経過日数（＝処理までの日数とみなす）。"""
    return (BASE_DATE - date.fromisoformat(row["created_at"])).days


def impact_facts() -> dict:
    """改定案の影響を実データから計算する（決定的）。"""
    rows = load_expenses()
    days = {r["expense_id"]: elapsed_days(r) for r in rows}
    return {
        "rows": rows,
        "days": days,
        # 金額基準の影響：1万円以上5万円未満＝新たに事前承認が必要になる
        "newly_approval": [r for r in rows if NEW_APPROVAL <= r["amount"] < OLD_APPROVAL],
        "already_approval": [r for r in rows if r["amount"] >= OLD_APPROVAL],
        # 期限の影響：6〜10日＝旧基準では期限内、新基準では超過
        "newly_late": [r for r in rows
                       if NEW_DEADLINE_DAYS < days[r["expense_id"]] <= OLD_DEADLINE_DAYS],
        "already_late": [r for r in rows if days[r["expense_id"]] > OLD_DEADLINE_DAYS],
    }


def fmt(rows: list[dict]) -> str:
    if not rows:
        return "該当なし"
    return "、".join(f"{r['expense_id']}（{r['amount']:,} 円 / {r['category']}）" for r in rows)


def render_report(facts: dict, *, policy: bool = True, amount: bool = True,
                  deadline: bool = True, note: str = "") -> str:
    """影響調査レポートを組み立てる。

    policy / amount / deadline を False にすると、その観点が欠けたレポートになる。
    「どの観点が落ちたか」を成果物の側で表現するために引数にしている。
    """
    out = ["# 経費精算規程 改定案の影響調査", ""]
    if policy:
        out += [
            "## 前提とした現行規程",
            f"- 事前承認: 1件 {OLD_APPROVAL:,} 円以上",
            f"- 申請期限: 支出日から {OLD_DEADLINE_DAYS} 日以内",
            '- 出典: get_policy("経費精算")',
            "",
        ]
    out += [
        "## 改定案",
        f"- 事前承認の基準額: {OLD_APPROVAL:,} 円 → {NEW_APPROVAL:,} 円",
        f"- 申請期限: {OLD_DEADLINE_DAYS} 日 → {NEW_DEADLINE_DAYS} 日",
        "",
        "## 影響1: 事前承認の対象",
    ]
    if amount:
        out += [
            f"- 新たに事前承認が必要になる申請: {fmt(facts['newly_approval'])}"
            f"（{len(facts['newly_approval'])} 件）",
            f"- すでに対象の申請: {fmt(facts['already_approval'])}"
            f"（{len(facts['already_approval'])} 件）",
        ]
    else:
        out.append("- 新たに事前承認が必要になる申請: 特定できませんでした（申請一覧を参照していません）")
    out += ["", "## 影響2: 申請期限"]
    if deadline:
        ids = "、".join(r["expense_id"] for r in facts["newly_late"])
        old = "、".join(r["expense_id"] for r in facts["already_late"])
        out += [
            f"- 新たに期限超過になる申請: {ids}（{len(facts['newly_late'])} 件）",
            f"- 元から超過していた申請: {old}（{len(facts['already_late'])} 件）",
        ]
    else:
        out.append("- 未調査（この観点は調べていません）")
    out += [
        "",
        "## 対応方針",
        "1. 施行日より前に起票済みの申請は旧基準で処理する",
        f"2. {NEW_APPROVAL:,} 円以上の申請には事前承認の入力欄を必須にする",
        f"3. 期限の短縮（{OLD_DEADLINE_DAYS} 日 → {NEW_DEADLINE_DAYS} 日）は"
        "社内周知から2週間の猶予を置く",
    ]
    if note:
        out += ["", "## 備考", f"- {note}"]
    return "\n".join(out) + "\n"


# 成果物の採点。「done で終わったか」ではなく「成果物が要件を満たすか」で測る
REPORT_CHECKS: tuple[tuple[str, str], ...] = (
    ("現行規程の出典を示している", '出典: get_policy("経費精算")'),
    ("改定案の金額基準を書いている", f"事前承認の基準額: {OLD_APPROVAL:,} 円 → {NEW_APPROVAL:,} 円"),
    ("金額基準の影響を特定している", "新たに事前承認が必要になる申請: EXP-"),
    ("申請期限の影響を特定している", "新たに期限超過になる申請: EXP-"),
    ("対応方針を書いている", "## 対応方針"),
)


def score_report(text: str) -> tuple[int, list[str]]:
    """満点は len(REPORT_CHECKS)。欠けた観点の名前も返す。"""
    missing = [label for label, marker in REPORT_CHECKS if marker not in text]
    return len(REPORT_CHECKS) - len(missing), missing


def main() -> None:
    facts = impact_facts()
    print("=== 実データから計算した影響（基準日 2026-08-15）===")
    print(f"{'expense_id':<12}{'金額':>10}{'経過日数':>8}  金額基準  申請期限")
    for r in facts["rows"]:
        d = facts["days"][r["expense_id"]]
        amount_mark = ("新たに対象" if r in facts["newly_approval"]
                       else "すでに対象" if r in facts["already_approval"] else "-")
        late_mark = ("新たに超過" if r in facts["newly_late"]
                     else "元から超過" if r in facts["already_late"] else "-")
        print(f"{r['expense_id']:<12}{r['amount']:>10,}{d:>8}  {amount_mark:<10}{late_mark}")
    print()
    print(f"新たに事前承認が必要: {len(facts['newly_approval'])} 件 / "
          f"すでに対象: {len(facts['already_approval'])} 件")
    print(f"新たに期限超過: {len(facts['newly_late'])} 件 / "
          f"元から超過: {len(facts['already_late'])} 件")
    print()
    report = render_report(facts)
    score, missing = score_report(report)
    print(f"=== 満点のレポート（{score}/{len(REPORT_CHECKS)} 点）===")
    print(report)
    if missing:
        print(f"欠けている観点: {missing}")


if __name__ == "__main__":
    main()
