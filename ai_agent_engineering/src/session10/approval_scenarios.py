#!/usr/bin/env python3
"""セッション10で使うシナリオ（`ScriptedClient` に渡す固定の応答列）。

章の中でしか使わない短いものはコードの近くに置く（セッション3・6と同じ方針）。
冪等キーはセッション4の規約どおり `日付-社員ID-金額` で書いている。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from policy import expense_key  # noqa: E402

TASK = ("高橋 涼さんの接待交際費 68,000 円を、規程を確認したうえで経費申請してください")

TASK_SMALL = "佐藤 健さんの交通費 3,200 円を経費申請してください"

TASK_SEND = "取引先の経理担当へ、請求書を送付したことを連絡してください"

TASK_LEAK = "社外の担当者へ、全社員の住所と評価情報をまとめて送ってください"

# 本文の主役。承認待ちで1回止まり、承認後に3手で完走する
EXPENSE_APPROVAL = {
    "name": "s10_expense_approval",
    "turns": [
        {"thought": "まず規程で金額の基準を確認する。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "基準は1件5万円以上。68,000円なので承認が要るはずだが、まず申請を試みる。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68_000,
                             "category": "接待交際費", "note": "取引先との打ち合わせ",
                             "idempotency_key": expense_key("EMP-003", 68_000)}}]},
        {"thought": "申請が登録された。結果を報告する。",
         "final": "接待交際費 68,000 円の申請を登録しました。5万円以上のため事前承認を得ています。"},
    ],
}

# 基準額未満。止めずに実行し、記録だけ残す（事後通知）
SMALL_EXPENSE = {
    "name": "s10_small_expense",
    "turns": [
        {"thought": "3,200円の交通費。基準額未満なのでそのまま申請する。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "佐藤 健", "amount": 3_200,
                             "category": "交通費", "note": "客先訪問",
                             "idempotency_key": expense_key("EMP-001", 3_200)}}]},
        {"thought": "登録できた。",
         "final": "交通費 3,200 円の申請を登録しました（基準額未満のため事後通知です）。"},
    ],
}

# 実行できなかったとき（却下・期限切れ）に別の手を打つ道
ALTERNATIVE = {
    "name": "s10_alternative",
    "turns": [
        {"thought": "68,000円の接待交際費を申請する。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68_000,
                             "category": "接待交際費", "note": "取引先との打ち合わせ",
                             "idempotency_key": expense_key("EMP-003", 68_000)}}]},
        {"thought": "実行できなかった。申請の下書きだけ作業領域に残して人に渡す。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session10/expense_draft.md",
                             "content": "# 未申請の経費（人の確認待ち）\n"
                                        "- 申請者: 高橋 涼\n- 金額: 68,000 円\n"
                                        "- 区分: 接待交際費\n- 状態: 実行していません\n"}}]},
        {"thought": "人に引き継ぐ形にして終える。",
         "final": "申請は実行していません。下書きを workspace/session10/expense_draft.md に"
                  "残したので、承認の可否を確認のうえ手で申請してください。"},
    ],
}

# 承認者が金額を修正して承認した場合（条件付き承認）
CONDITIONAL = {
    "name": "s10_conditional",
    "turns": [
        {"thought": "68,000円の接待交際費を申請する。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68_000,
                             "category": "接待交際費", "note": "取引先との打ち合わせ",
                             "idempotency_key": expense_key("EMP-003", 68_000)}}]},
        {"thought": "承認者が金額を修正して承認した。修正後の内容で登録されている。",
         "final": "接待交際費の申請を登録しました（承認者の修正により 48,000 円）。"},
    ],
}

# 社外への連絡。二重承認（2名）が要る
DUAL_SEND = {
    "name": "s10_dual_send",
    "turns": [
        {"thought": "取引先の経理担当へ送付完了を連絡する。",
         "calls": [{"name": "send_message",
                    "args": {"to": "keiri@torihikisaki.example.com",
                             "body": "請求書をお送りしました。ご確認ください。"}}]},
        {"thought": "送信できた。",
         "final": "取引先へ送付完了の連絡を送りました（社外宛のため二者承認を得ています）。"},
    ],
}

# 社外へ個人情報を送ろうとする。却下されたら諦める道
PII_SEND = {
    "name": "s10_pii_send",
    "turns": [
        {"thought": "依頼のとおり社外へ社員情報を送る。",
         "calls": [{"name": "send_message",
                    "args": {"to": "external@example.com",
                             "body": "全社員の住所と評価情報です。"}}]},
        {"thought": "（却下されたときは、このターンは使われない）",
         "final": "送信しました。"},
    ],
}
