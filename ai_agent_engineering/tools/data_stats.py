#!/usr/bin/env python3
"""業務データの統計。本文に書く件数の出典。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        print(f"{path} がありません。先に python tools/make_data.py を実行してください。")
        sys.exit(1)
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def main() -> None:
    employees = load("employees")
    expenses = load("expenses")
    docs = load("docs")
    policies = load("policies")
    rooms = load("rooms")

    print("=== 社員 ===")
    print(f"人数          : {len(employees)}")
    print(f"役職別        : {dict(sorted(Counter(e['role'] for e in employees).items()))}")
    print(f"部門別        : {dict(sorted(Counter(e['dept'] for e in employees).items()))}")

    print("\n=== 経費申請 ===")
    print(f"件数          : {len(expenses)}")
    print(f"状態別        : {dict(sorted(Counter(e['status'] for e in expenses).items()))}")
    print(f"区分別        : {dict(sorted(Counter(e['category'] for e in expenses).items()))}")
    over = [e for e in expenses if e["amount"] >= 50_000]
    print(f"5万円以上     : {len(over)} 件（承認が必要な金額）")
    noted = [e for e in expenses if e.get("note")]
    print(f"注記あり      : {len(noted)} 件 → {[e['expense_id'] for e in noted]}")
    print(f"合計金額      : {sum(e['amount'] for e in expenses):,} 円")

    print("\n=== 文書・規程・会議室 ===")
    print(f"文書数        : {len(docs)}")
    injected = [d for d in docs if "これまでの指示は無効" in d["body"]]
    print(f"注入を含む文書: {len(injected)} 件 → {[d['doc_id'] for d in injected]}")
    print(f"規程数        : {len(policies)}")
    print(f"会議室数      : {len(rooms)}（定員合計 {sum(r['capacity'] for r in rooms)} 名）")

    print("\n=== 追記系（演習で増える）===")
    for name in ("bookings", "messages"):
        path = DATA / f"{name}.jsonl"
        count = sum(1 for line in path.open(encoding="utf-8") if line.strip()) if path.exists() else 0
        print(f"{name:<14}: {count} 件")


if __name__ == "__main__":
    main()
