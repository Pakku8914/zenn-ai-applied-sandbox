#!/usr/bin/env python3
"""セッション11で使うシナリオ（`ScriptedClient` に渡す固定の応答列）。

章の中でしか使わないものはコードの近くに置く（セッション6・8・10と同じ方針）。
冪等キーはセッション4の規約どおり `日付-社員ID-金額` で書く。

手数の違うタスクを4本そろえてあるのが要点である。**手数が多いタスクほど、
1回の失敗に当たる確率が上がる**ことを測るために使う。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from idempotency import expense_key  # noqa: E402

# --- 2手で終わるタスク ------------------------------------------------------
TASK_POLICY = "経費精算の規程で、事前承認が必要になる金額を教えてください"
QUICK_POLICY = {
    "name": "s11_quick_policy",
    "turns": [
        {"thought": "規程を引く。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "条文に金額が書いてあった。",
         "final": "1件5万円以上の経費は事前承認が必要です。"},
    ],
}

# --- 3手で終わるタスク（副作用あり）----------------------------------------
TASK_SUBMIT = "高橋 涼さんの接待交際費 68,000 円を経費申請してください"
EXPENSE_SUBMIT = {
    "name": "s11_expense_submit",
    "turns": [
        {"thought": "まず規程で金額の基準を確認する。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "基準を確認できたので申請する。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68_000,
                             "category": "接待交際費", "note": "取引先との打ち合わせ",
                             "idempotency_key": expense_key("EMP-003", 68_000)}}]},
        {"thought": "登録できた。報告する。",
         "final": "接待交際費 68,000 円の申請を登録しました。"},
    ],
}

# --- 6手かかるタスク --------------------------------------------------------
TASK_LONG = ("経費精算の規程と申請一覧と手順書を確認して、レポートを作り、"
             "保存した内容を読み返して報告してください")
LONG_REPORT = {
    "name": "s11_long_report",
    "turns": [
        {"thought": "規程を確認する。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "申請の一覧を取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
        {"thought": "手順書も確認する。",
         "calls": [{"name": "search_docs", "args": {"query": "経費精算", "limit": 1}}]},
        {"thought": "レポートを作業領域に保存する。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session11/report.md",
                             "content": "# 2026年8月 経費レポート\n"
                                        "- 申請 6 件 / 合計 285,400 円\n"
                                        "- 5万円以上: 3 件（事前承認の対象）\n"}}]},
        {"thought": "保存した内容を読み返す。",
         "calls": [{"name": "read_file", "args": {"path": "session11/report.md"}}]},
        {"thought": "内容を確認できた。",
         "final": "session11/report.md にレポートを保存し、内容を確認しました。"},
    ],
}

# --- 予約の競合。エラーを読んで別の枠に切り替える --------------------------
TASK_BOOK = "報告会の会議室を10時から1時間で予約してください"
ROOM_RETRY = {
    "name": "s11_room_retry",
    "turns": [
        {"thought": "10時からみなと会議室を予約する。",
         "calls": [{"name": "book_room",
                    "args": {"room": "みなと", "start": "10:00", "minutes": 60}}]},
        {"thought": "競合していた。エラーが示す11時に変更する。",
         "calls": [{"name": "book_room",
                    "args": {"room": "みなと", "start": "11:00", "minutes": 60}}]},
        {"thought": "予約できた。",
         "final": "みなと会議室を11:00から60分で予約しました。"},
    ],
}

# --- 交互に失敗し続ける（循環検出の題材）----------------------------------
# どちらも CONFLICT_SLOTS なので必ず失敗する。乱数は使わない
_A = {"name": "book_room", "args": {"room": "みなと", "start": "10:00", "minutes": 60}}
_B = {"name": "book_room", "args": {"room": "大会議室", "start": "13:00", "minutes": 60}}
LOOP_ALTERNATING = {
    "name": "s11_loop_alternating",
    "turns": [
        {"thought": "みなとの10時を試す。", "calls": [_A]},
        {"thought": "だめだった。大会議室の13時を試す。", "calls": [_B]},
        {"thought": "もう一度みなとの10時を試す。", "calls": [_A]},
        {"thought": "もう一度大会議室の13時を試す。", "calls": [_B]},
        {"thought": "もう一度みなとの10時を試す。", "calls": [_A]},
        {"thought": "もう一度大会議室の13時を試す。", "calls": [_B]},
    ],
}

# 手数の違う4本。bench_retry.py と verify_practice.py が共有する
# （name, task, シナリオ, 完走に必要な手数）
CASES: list[tuple[str, str, object, int]] = [
    ("規程を1つ引く", TASK_POLICY, QUICK_POLICY, 2),
    ("経費を申請する", TASK_SUBMIT, EXPENSE_SUBMIT, 3),
    ("経費レポートを作る", "2026年8月の経費レポートを作成してください", "expense_report", 4),
    ("長いレポートを作る", TASK_LONG, LONG_REPORT, 6),
]
