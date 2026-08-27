#!/usr/bin/env python3
"""セッション7のツール群 — わざと「大きな結果」を返すツールを足す。

`agentkit` は1行も変更しない。`agentkit.tools.Tool` / `ToolRegistry` と
`agentkit.biztools.write_file` をそのまま使い、監査ログという**桁の大きな
ツール結果**をこの層で用意する。コンテキストが溢れる現象を、読者の環境でも
必ず同じ手数・同じ記録数で起こすためである。

すべてのツール結果は `records.py` の固定幅レコードで返す（1記録 33文字）。

    python src/session07/bigtools.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA, write_file  # noqa: E402
from agentkit.tools import Tool, ToolError, ToolRegistry  # noqa: E402
from records import record  # noqa: E402

LINES_PER_MONTH = 120          # 1か月ぶんの監査ログの行数
CONSTRAINT_LINE = 31           # 監査方針の追記が紛れている行番号
EXPENSE_LINE_FROM = 11         # 実際の申請を参照する行の開始位置

# ログに紛れ込んでいる監査方針の追記（実務でもよくある「前任者のメモ」）
LOG_CONSTRAINTS = {
    "2026-07": "必ず注記のある申請も対象に。",
    "2026-08": "上限: 監査は6件まで。",
}

# 規程から読み取る制約。data/policies.jsonl の本文と一致していることを検証する
POLICY_RECORDS = {
    "経費精算": (
        ("制約", "1件5万円以上は必ず事前承認。", "5万円以上"),
        ("制約", "支出日から10日以内に申請。", "10日以内"),
        ("規程", "領収書の添付が必要。", "領収書"),
    ),
}

SHORT_STATUS = {"submitted": "申請中", "approved": "承認済", "rejected": "差戻し"}


def _load(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        raise ToolError(f"{path.name} がありません。`python tools/make_data.py` を実行してください。")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _month_expenses(month: str) -> list[dict]:
    return [r for r in _load("expenses") if r["created_at"].startswith(month)]


# ---------------------------------------------------------------------------
# 読み取り系
# ---------------------------------------------------------------------------
def fetch_audit_log(month: str, lines: int = LINES_PER_MONTH) -> str:
    """指定した月の監査ログを返す。**これがコンテキストを食い潰す主犯**。

    行の内訳（決定的）:
      - 11行目から、その月に起票された申請を参照する行
      - 31行目に、監査方針の追記（制約）が1行だけ紛れている
      - 残りは定型行
    """
    if month not in LOG_CONSTRAINTS:
        raise ToolError(
            f"月 '{month}' のログはありません。指定できる月: {', '.join(LOG_CONSTRAINTS)}")
    if lines < CONSTRAINT_LINE:
        raise ToolError(f"lines は {CONSTRAINT_LINE} 以上にしてください（方針の追記が {CONSTRAINT_LINE} 行目にあります）。")
    mm = month[5:7]
    rows = _month_expenses(month)
    refs = {EXPENSE_LINE_FROM + i: r for i, r in enumerate(rows)}
    out: list[str] = []
    for i in range(1, lines + 1):
        head = f"{mm}-{i:03d} "
        if i == CONSTRAINT_LINE:
            out.append(record("制約", head + LOG_CONSTRAINTS[month]))
        elif i in refs:
            r = refs[i]
            out.append(record("ログ", f"{head}{r['expense_id']} {r['amount']}円 起票"))
        else:
            out.append(record("ログ", head + "定例の処理。問題なし。"))
    return "\n".join(out)


def read_audit_policy(topic: str) -> str:
    """監査に使う規程を読む。制約は制約として札を付けて返す。"""
    if topic not in POLICY_RECORDS:
        raise ToolError(f"'{topic}' の監査規程はありません。指定できる項目: {', '.join(POLICY_RECORDS)}")
    rule = next((r["rule"] for r in _load("policies") if r["topic"] == topic), "")
    out = []
    for kind, body, must_appear in POLICY_RECORDS[topic]:
        if must_appear not in rule:
            # 規程の本文が変わったら気づけるようにする（記録が実データから離れないため）
            raise ToolError(f"規程の本文に '{must_appear}' が見つかりません。記録の定義を見直してください。")
        out.append(record(kind, body))
    return "\n".join(out)


def list_expense_records(status: str = "all") -> str:
    """経費申請の一覧を記録形式で返す。判定に使う材料はこれだけ。"""
    rows = _load("expenses")
    if status != "all":
        if status not in SHORT_STATUS:
            raise ToolError(f"status は all / {' / '.join(SHORT_STATUS)} のいずれかです。")
        rows = [r for r in rows if r["status"] == status]
    out = []
    for r in rows:
        mark = " 注記" if r["note"] else ""
        out.append(record("一覧", f"{r['expense_id']} {r['amount']} "
                                  f"{SHORT_STATUS[r['status']]} {r['created_at'][5:]}{mark}"))
    return "\n".join(out) if out else record("一覧", "該当する申請はありません。")


# ---------------------------------------------------------------------------
# 書き込み系
# ---------------------------------------------------------------------------
def write_audit_report(path: str, content: str) -> str:
    """監査レポートを作業領域に保存する（`agentkit.biztools.write_file` に委譲）。"""
    write_file(path, content)
    return record("結果", f"レポートを保存: {len(content)}字")


def build_registry07() -> ToolRegistry:
    """セッション7で使うツールだけを登録したレジストリ。"""
    return ToolRegistry([
        Tool("read_audit_policy",
             "監査に使う規程を読み、制約を札付きの記録で返します。",
             {"type": "object",
              "properties": {"topic": {"type": "string", "description": "規程の項目名"}},
              "required": ["topic"]},
             read_audit_policy, tags=("read",)),
        Tool("fetch_audit_log",
             "指定した月の監査ログを返します。結果は非常に大きくなります。",
             {"type": "object",
              "properties": {"month": {"type": "string", "description": "対象月（2026-07 など）"},
                             "lines": {"type": "integer", "description": "取得行数（既定120）"}},
              "required": ["month"]},
             fetch_audit_log, tags=("read",)),
        Tool("list_expense_records",
             "経費申請の一覧を記録形式で返します。判定の材料に使います。",
             {"type": "object",
              "properties": {"status": {"type": "string",
                                        "enum": ["all", "submitted", "approved", "rejected"]}}},
             list_expense_records, tags=("read",)),
        Tool("write_audit_report",
             "監査レポートを作業領域に保存します。",
             {"type": "object",
              "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
              "required": ["path", "content"]},
             write_audit_report, idempotent=True, tags=("write",)),
    ])


if __name__ == "__main__":
    from records import tokens, to_records

    for month in LOG_CONSTRAINTS:
        recs = to_records(fetch_audit_log(month))
        print(f"{month}: {len(recs)} 記録 / 近似 {tokens(recs)} トークン")
        for i in (0, EXPENSE_LINE_FROM - 1, CONSTRAINT_LINE - 1):
            print(f"  {recs[i]}")
    policy = to_records(read_audit_policy("経費精算"))
    expenses = to_records(list_expense_records("all"))
    print(f"規程: {len(policy)} 記録 / 一覧: {len(expenses)} 記録")
    for r in expenses:
        print(f"  {r}")
