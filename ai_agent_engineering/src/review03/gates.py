#!/usr/bin/env python3
"""復習03：承認の判定と、承認したことの証拠（S04 × S10）。

レビューで問うのは2つである。

  1. **止める基準**が規程と合っているか（止め損ない／余計な停止をどちらも数える）
  2. **止めた証拠**が後から検証できるか（ハッシュ鎖で何が検出でき、何ができないか）

    python src/review03/gates.py

副作用は出さない（判定を呼ぶだけで、ツールは実行しない）。監査ログは
`traces/audit/REVIEW03-audit.jsonl` に書く（S10 のログは触らない）。

`agentkit` と `src/session10/` は1行も変更しない。
"""

from __future__ import annotations

from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from audit import AuditLog, rewrite_rows, tamper  # noqa: E402  (S10)
from policy import MODE_LABEL, decide, expense_key  # noqa: E402  (S10)
from spec import POLICY_THRESHOLD  # noqa: E402

STOPPING = ("approve", "dual")   # 「事前承認以上」＝実行の前に人を待つ段階
LOOSE_THRESHOLD = 100_000        # レビュー前の仕様が持っていた基準

# 月次締めの1回の走行で出る12件の呼び出し（S10 の判定表にかける材料）
CALLS: tuple[tuple[str, ToolCall], ...] = (
    ("規程を読む",
     ToolCall("g1", "get_policy", {"topic": "経費精算"})),
    ("経費申請の一覧を読む",
     ToolCall("g2", "list_expenses", {"status": "all"})),
    ("手順書を検索する",
     ToolCall("g3", "search_docs", {"query": "月次レポート", "limit": 1})),
    ("前回のレポートを読む",
     ToolCall("g4", "read_file", {"path": "report.md"})),
    ("レポートを書く",
     ToolCall("g5", "write_file", {"path": "report.md", "content": "月次レポート"})),
    ("3,200 円の交通費を申請する",
     ToolCall("g6", "submit_expense",
              {"employee": "佐藤 健", "amount": 3_200, "category": "交通費",
               "idempotency_key": expense_key("EMP-001", 3_200)})),
    ("68,000 円の接待交際費を申請する",
     ToolCall("g7", "submit_expense",
              {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "idempotency_key": expense_key("EMP-003", 68_000)})),
    ("会議室を予約する",
     ToolCall("g8", "book_room", {"room": "うみかぜ", "start": "11:00", "minutes": 60})),
    ("経理部へ共有する",
     ToolCall("g9", "send_message", {"to": "経理部", "body": "月次レポートを共有します。"})),
    ("取引先へ送付の連絡をする",
     ToolCall("g10", "send_message", {"to": "keiri@torihikisaki.example.com",
                                      "body": "請求書をお送りしました。"})),
    ("集計コードを隔離環境で実行する",
     ToolCall("g11", "run_python", {"code": "print(1)"})),
    ("社員情報を引く",
     ToolCall("g12", "get_employee", {"employee_id": "EMP-001"})),
)


# ---------------------------------------------------------------------------
# 1. 止める基準（問題5でここを自分で書く）
# ---------------------------------------------------------------------------
def by_tool(call: ToolCall, registry) -> bool:
    """ツール単位の判定（`agentkit` の既定）。止めるなら True。

    レジストリに無いツールは `requires_approval` を持たないので、**素通しになる**。
    """
    tool = registry.get(call.name)
    return bool(tool is not None and tool.requires_approval)


def by_operation(call: ToolCall, registry, threshold: int) -> str:
    """操作単位の判定（S10）。段階（auto / notify / approve / dual）を返す。"""
    return decide(call, registry.get(call.name), threshold_yen=threshold).mode


def stops_by_operation(call: ToolCall, registry, threshold: int) -> bool:
    return by_operation(call, registry, threshold) in STOPPING


def gaps(stop_fn, registry) -> list[str]:
    """止めるべきなのに止めないもの。

    「止めるべき」の基準は**規程どおりの判定**（操作単位・5万円）に置く。
    基準を判定の実装から取ると、実装のバグが基準ごと動いてしまう。
    """
    return [label for label, call in CALLS
            if stops_by_operation(call, registry, POLICY_THRESHOLD) and not stop_fn(call)]


def over_stops(stop_fn, registry) -> list[str]:
    """止めなくてよいのに止めるもの（承認者が中身を読まなくなる原因）。"""
    return [label for label, call in CALLS
            if not stops_by_operation(call, registry, POLICY_THRESHOLD) and stop_fn(call)]


def judgements(registry=None) -> list[dict]:
    """12件を3つの判定にかけた結果を1行ずつ返す。"""
    registry = registry or build_registry()
    out = []
    for index, (label, call) in enumerate(CALLS, start=1):
        out.append({
            "#": index, "操作": label,
            "ツール単位": "止める" if by_tool(call, registry) else "通す",
            "操作単位（規程）": MODE_LABEL[by_operation(call, registry, POLICY_THRESHOLD)],
            "操作単位（10万円）": MODE_LABEL[by_operation(call, registry, LOOSE_THRESHOLD)],
        })
    return out


def summary(registry=None) -> list[dict]:
    """3つの判定について、止める件数・止め損ない・余計な停止を数える。"""
    registry = registry or build_registry()
    variants = (
        ("ツール単位", lambda c: by_tool(c, registry)),
        (f"操作単位（基準 {POLICY_THRESHOLD:,} 円）",
         lambda c: stops_by_operation(c, registry, POLICY_THRESHOLD)),
        (f"操作単位（基準 {LOOSE_THRESHOLD:,} 円）",
         lambda c: stops_by_operation(c, registry, LOOSE_THRESHOLD)),
    )
    return [{"判定": name,
             "止める件数": sum(1 for _l, c in CALLS if stop_fn(c)),
             "止め損ない": gaps(stop_fn, registry),
             "余計に止める": over_stops(stop_fn, registry)}
            for name, stop_fn in variants]


# ---------------------------------------------------------------------------
# 2. 止めた証拠（問題7でここを自分で書く）
# ---------------------------------------------------------------------------
@dataclass
class TailGuard:
    """監査ログの末尾が切り落とされていないかを見張る。

    ハッシュ鎖は「行と行のつながり」しか守らないので、末尾をまとめて捨てられると
    残った部分は健全に見える。**行数という別の記録**と突き合わせて初めて気づける。
    """

    expected: int

    def verify(self, log: AuditLog) -> tuple[bool, str]:
        ok, index = log.verify_chain()
        if not ok:
            return False, f"鎖が {index} 行目で壊れています"
        actual = len(log.rows())
        if actual < self.expected:
            return False, f"末尾が {self.expected - actual} 行切り落とされています"
        if actual > self.expected:
            return False, f"記録していない行が {actual - self.expected} 行増えています"
        return True, "健全"


def build_log(task_id: str = "REVIEW03-audit") -> tuple[AuditLog, list[dict]]:
    """依頼・承認・実行の3行を書いたログと、その正しい内容を返す。"""
    log = AuditLog(task_id)
    log.reset()
    log.append("requested", tool="submit_expense", mode="approve",
               detail="金額 68,000 円 ≧ 基準 50,000 円")
    log.append("approved", actor="鈴木 彩", tool="submit_expense", mode="approve",
               detail="1/1 内容を確認")
    log.append("executed", tool="submit_expense", mode="approve", detail="EXP-0007")
    return log, log.rows()


def chain_cases() -> list[dict]:
    """改ざんの4つの形に対して、鎖だけの検査と件数つきの検査を比べる。"""
    log, intact = build_log()
    guard = TailGuard(len(intact))
    out: list[dict] = []

    def record(label: str) -> None:
        ok, index = log.verify_chain()
        guard_ok, note = guard.verify(log)
        out.append({"改ざん": label, "行数": len(log.rows()),
                    "鎖だけの検査": "検出" if not ok else "健全",
                    "壊れた行": index, "件数つきの検査": "検出" if not guard_ok else "健全",
                    "備考": note})

    record("なし（正しいログ）")
    tamper(log, 1, "2/2 として承認されたことにする")
    record("途中の1行を書き換える")
    rewrite_rows(log, [intact[0], intact[2]])
    record("途中の1行を消す")
    rewrite_rows(log, [intact[0], intact[0], intact[1], intact[2]])
    record("同じ行を挿入する")
    rewrite_rows(log, intact[:2])
    record("末尾の1行を切り落とす")
    rewrite_rows(log, intact)   # 後片付け（正しい内容に戻す）
    return out


# ---------------------------------------------------------------------------
def render() -> str:
    lines = [f"=== 承認の判定（{len(CALLS)} 件の呼び出し）===",
             "# | 操作 | ツール単位 | 操作単位（規程） | 操作単位（10万円）"]
    for row in judgements():
        lines.append(f"{row['#']} | {row['操作']} | {row['ツール単位']} | "
                     f"{row['操作単位（規程）']} | {row['操作単位（10万円）']}")
    lines += ["", "=== 判定のずれ ===", "判定 | 止める件数 | 止め損ない | 余計に止める"]
    for row in summary():
        lines.append(f"{row['判定']} | {row['止める件数']} | "
                     f"{'・'.join(row['止め損ない']) or 'なし'} | "
                     f"{'・'.join(row['余計に止める']) or 'なし'}")
    lines += ["", "=== 承認したことの証拠（監査ログの検査）===",
              "改ざん | 行数 | 鎖だけの検査 | 件数つきの検査"]
    for row in chain_cases():
        lines.append(f"{row['改ざん']} | {row['行数']} | {row['鎖だけの検査']} | "
                     f"{row['件数つきの検査']}")
    return "\n".join(lines)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
