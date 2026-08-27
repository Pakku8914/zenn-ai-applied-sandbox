#!/usr/bin/env python3
"""セッション10：どこで止めるかを決める判定表（可逆性 × 影響範囲）。

承認は「厳しくすればよい」ものではない。全部を承認対象にすると、承認者は中身を
読まずに押すようになる（本文のアンチパターン）。操作の属性から段階を機械的に決め、
**なぜその段階なのか**を言葉で残すのがこの層の役目である。

自律性の4段階:
  auto    自動実行  … そのまま実行する（記録は軌跡に残る）
  notify  事後通知  … 実行してから監査ログに残す
  approve 事前承認  … 実行前に1名の承認を待つ
  dual    二重承認  … 実行前に2名の承認を待つ

`agentkit` は1行も変更しない。`Tool.requires_approval` は「ツール単位の粗い宣言」で
あって判定そのものではないため、ここで引数まで見た判定を作る。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.models import ToolCall  # noqa: E402

# ---------------------------------------------------------------------------
# 段階と軸のラベル
# ---------------------------------------------------------------------------
MODES = ("auto", "notify", "approve", "dual")
MODE_LABEL = {"auto": "自動実行", "notify": "事後通知",
              "approve": "事前承認", "dual": "二重承認"}

REVERSIBILITY = ("reversible", "costly", "irreversible")
REVERSIBILITY_LABEL = {"reversible": "取り消せる",
                       "costly": "取り消せるが痕跡が残る",
                       "irreversible": "取り消せない"}

BLAST = ("self", "team", "external")
BLAST_LABEL = {"self": "自分の作業領域", "team": "社内", "external": "社外"}

# 可逆性 × 影響範囲 → 既定の段階。ここが「止める基準」の本体
MATRIX: dict[tuple[str, str], str] = {
    ("reversible", "self"): "auto",
    ("reversible", "team"): "auto",
    ("reversible", "external"): "approve",
    ("costly", "self"): "auto",
    ("costly", "team"): "notify",
    ("costly", "external"): "approve",
    ("irreversible", "self"): "notify",
    ("irreversible", "team"): "approve",
    ("irreversible", "external"): "dual",
}

# 規程「経費精算」から取った金額基準。1件5万円以上は事前承認が必要
THRESHOLD_YEN = 50_000
# 承認されないまま放置されたときに諦める時間（実時間では待たない。時計を注入する）
TTL_HOURS = 24
# 個人情報の手がかり（粗い検出器。正面から扱うのはセッション12）
PII_MARKERS = ("住所", "評価", "個人情報")


@dataclass(frozen=True)
class Operation:
    """操作の属性。ツール名ごとに1行で宣言する。"""

    reversibility: str
    blast: str
    note: str = ""


OPERATIONS: dict[str, Operation] = {
    "search_docs": Operation("reversible", "self", "読むだけ"),
    "get_policy": Operation("reversible", "self", "読むだけ"),
    "list_expenses": Operation("reversible", "self", "読むだけ"),
    "get_employee": Operation("reversible", "self", "読むだけ（見える範囲は権限で絞る）"),
    "read_file": Operation("reversible", "self", "読むだけ"),
    "write_file": Operation("costly", "self", "上書きは戻せないが作業領域の中"),
    "book_room": Operation("costly", "team", "取り消せるが他人の予定表に出る"),
    "submit_expense": Operation("irreversible", "team", "取り下げには承認者の手間がかかる"),
    "send_message": Operation("irreversible", "team", "送信は取り消せない"),
    "delete_record": Operation("irreversible", "team", "復元できない"),
}


@dataclass
class Decision:
    """判定の結果。段階と、その段階になった理由を必ずセットで持つ。"""

    mode: str
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return MODE_LABEL[self.mode]

    def to_dict(self) -> dict:
        return {"mode": self.mode, "reasons": list(self.reasons)}


def escalate(current: str, floor: str) -> str:
    """厳しい方を採る（引き上げ）。"""
    return MODES[max(MODES.index(current), MODES.index(floor))]


def relax(current: str, ceiling: str) -> str:
    """緩い方を採る（引き下げ）。根拠がある場合だけ使う。"""
    return MODES[min(MODES.index(current), MODES.index(ceiling))]


def is_external(to: str) -> bool:
    """宛先が社外かどうか。社内チャットは氏名や部署名、社外はメールアドレス。"""
    return "@" in to


def contains_pii(args: dict) -> bool:
    blob = json.dumps(args, ensure_ascii=False)
    return any(marker in blob for marker in PII_MARKERS)


def expense_key(employee_id: str, amount: int, date: str = "2026-08-15") -> str:
    """セッション4の冪等キー（日付-社員ID-金額）。

    承認の照合ハッシュとは目的が逆である（本文「2つの鍵を混同しない」を参照）。
      - 冪等キー … 同じ意図の申請なら**同じ値**になってほしい（受け取る側が重複を弾く）
      - 照合ハッシュ … 1文字違えば**別の値**になってほしい（呼ぶ側が同一性を確かめる）
    """
    return f"{date}-{employee_id}-{amount}"


def decide(call: ToolCall, tool=None, threshold_yen: int = THRESHOLD_YEN) -> Decision:
    """1回のツール呼び出しに対して自律性の段階を決める。

    引数まで見るのが要点。同じ `submit_expense` でも 3,200 円と 68,000 円で段階が違う。
    """
    op = OPERATIONS.get(call.name)
    if op is None:
        # 分類されていない操作は止める側に倒す（許可リストと同じ考え方）
        return Decision("approve", [f"未登録の操作 '{call.name}'。分類できないものは止める側に倒す"])

    mode = MATRIX[(op.reversibility, op.blast)]
    reasons = [f"{REVERSIBILITY_LABEL[op.reversibility]} × {BLAST_LABEL[op.blast]}"
               f" → {MODE_LABEL[mode]}（{op.note}）"]

    if call.name == "submit_expense":
        raw = call.args.get("amount")
        amount = raw if isinstance(raw, int) else 0
        if amount >= threshold_yen:
            mode = escalate(mode, "approve")
            reasons.append(f"金額 {amount:,} 円 ≧ 基準 {threshold_yen:,} 円"
                           "（規程「経費精算」: 1件5万円以上は事前承認が必要）")
        else:
            mode = relax(mode, "notify")
            reasons.append(f"金額 {amount:,} 円 < 基準 {threshold_yen:,} 円。"
                           "規程の承認対象ではないので事後通知に下げる")

    if call.name == "send_message" and is_external(str(call.args.get("to", ""))):
        mode = escalate(mode, "dual")
        reasons.append("宛先が社外（規程「情報の持ち出し」: 社外への持ち出しは"
                       "所属長と情報セキュリティ室の二者承認）")

    if contains_pii(call.args):
        mode = escalate(mode, "dual")
        reasons.append("引数に個人情報の手がかり（住所・評価・個人情報）が含まれる")

    if tool is not None and getattr(tool, "requires_approval", False):
        raised = escalate(mode, "notify")
        if raised != mode:
            reasons.append("ツールが requires_approval を宣言しているので、最低でも記録を残す")
            mode = raised

    return Decision(mode, reasons)


# ---------------------------------------------------------------------------
# 表として出す（本文とレビュー資料に貼れる形）
# ---------------------------------------------------------------------------
def matrix_table() -> str:
    """可逆性 × 影響範囲のマトリクスを Markdown 表にする。"""
    header = "| 可逆性＼影響範囲 | " + " | ".join(BLAST_LABEL[b] for b in BLAST) + " |"
    sep = "| :--- | " + " | ".join(":---" for _ in BLAST) + " |"
    rows = [f"| {REVERSIBILITY_LABEL[r]} | "
            + " | ".join(MODE_LABEL[MATRIX[(r, b)]] for b in BLAST) + " |"
            for r in REVERSIBILITY]
    return "\n".join([header, sep, *rows])


SAMPLE_CALLS: list[tuple[str, ToolCall]] = [
    ("経費申請の一覧を読む",
     ToolCall("s1", "list_expenses", {"status": "all"})),
    ("作業領域に下書きを書く",
     ToolCall("s2", "write_file", {"path": "session10/draft.md", "content": "下書き"})),
    ("会議室を予約する",
     ToolCall("s3", "book_room", {"room": "みなと", "start": "11:00", "minutes": 60})),
    ("3,200円の交通費を申請する",
     ToolCall("s4", "submit_expense",
              {"employee": "佐藤 健", "amount": 3_200, "category": "交通費",
               "idempotency_key": expense_key("EMP-001", 3_200)})),
    ("68,000円の接待交際費を申請する",
     ToolCall("s5", "submit_expense",
              {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "idempotency_key": expense_key("EMP-003", 68_000)})),
    ("社内チャットへ連絡する",
     ToolCall("s6", "send_message", {"to": "経理部", "body": "月次レポートを共有します。"})),
    ("取引先へ連絡する",
     ToolCall("s7", "send_message", {"to": "keiri@torihikisaki.example.com",
                                     "body": "請求書をお送りしました。"})),
    ("社外へ社員情報を送る",
     ToolCall("s8", "send_message", {"to": "external@example.com",
                                     "body": "全社員の住所と評価情報です。"})),
    ("経費のレコードを削除する",
     ToolCall("s9", "delete_record", {"table": "expenses", "expense_id": "EXP-0002"})),
]


def survey() -> list[dict]:
    """代表的な操作を一括で判定する（本文の表の元データ）。"""
    rows = []
    for label, call in SAMPLE_CALLS:
        decision = decide(call)
        rows.append({"操作": label, "ツール": call.name, "mode": decision.mode,
                     "判定": decision.label, "根拠の要点": decision.reasons[-1]})
    return rows


if __name__ == "__main__":
    print(matrix_table())
    print()
    for row in survey():
        print(f"{row['判定']:<8} {row['操作']}")
        print(f"         └ {row['根拠の要点']}")
