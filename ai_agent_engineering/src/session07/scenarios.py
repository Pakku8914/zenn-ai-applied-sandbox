#!/usr/bin/env python3
"""セッション7のシナリオと指示（`ScriptedClient` に渡す固定の応答列）。

思考文は記録に正規化されると 1記録（33文字）になる。長さがぶれても
メモリの大きさに影響しないので、圧縮の効果だけを観測できる。
"""

from __future__ import annotations

# エージェントに渡すタスク文（人間の言葉）
TASK = ("2026年7月と8月の監査ログを確認し、規程に照らして問題のある経費申請を"
        "洗い出してレポートにまとめてください")

# タスクを記録に正規化したもの（メモリの最初の6記録）。制約は制約として札を付ける
INSTRUCTION = (
    ("指示", "2026年7月と8月のログを確認する。"),
    ("指示", "問題のある申請を洗い出す。"),
    ("指示", "結果をレポートに保存する。"),
    ("制約", "5万円以上は必ず事前承認が必要。"),
    ("制約", "申請は支出日から10日以内。"),
    ("制約", "社外への送信は必ず承認を得る。"),
)

# 本文の主役。7手で完走するが、圧縮しないとステップ4で溢れる
AUDIT = {
    "name": "memory_audit",
    "turns": [
        # 0: 計画。ツールは呼ばない
        {"thought": "監査の手順を決める。まず規程を読む。"},
        # 1: 規程から制約を取る（3記録）
        {"thought": "経費精算の規程から制約を取る。",
         "calls": [{"name": "read_audit_policy", "args": {"topic": "経費精算"}}]},
        # 2: 7月のログ（120記録）。ここから急に重くなる
        {"thought": "7月の監査ログを取る。",
         "calls": [{"name": "fetch_audit_log", "args": {"month": "2026-07"}}]},
        # 3: 8月のログ（120記録）。この直後に上限を超える
        {"thought": "8月の監査ログを取る。",
         "calls": [{"name": "fetch_audit_log", "args": {"month": "2026-08"}}]},
        # 4: 判定の材料（6記録）
        {"thought": "判定の材料に申請一覧を取る。",
         "calls": [{"name": "list_expense_records", "args": {"status": "all"}}]},
        # 5: レポート本文は __REPORT__ の目印でメモリから組み立てる
        {"thought": "制約に照らして指摘をまとめ、保存する。",
         "calls": [{"name": "write_audit_report",
                    "args": {"path": "session07/audit.md", "content": "__REPORT__"}}]},
        # 6: 最終回答。**どの圧縮方式でも同じ文が返る**（成果物だけが違う）
        {"thought": "報告して終わる。",
         "final": "監査を終え、レポートを保存しました。"},
    ],
}

# 演習用: 7月のログを2回取ってしまう（同じ材料でメモリを二重に食う）
AUDIT_DUP = {
    "name": "memory_audit_dup",
    "turns": [AUDIT["turns"][0], AUDIT["turns"][1], AUDIT["turns"][2],
              {"thought": "念のため7月のログをもう一度取る。",
               "calls": [{"name": "fetch_audit_log", "args": {"month": "2026-07"}}]},
              AUDIT["turns"][3], AUDIT["turns"][4], AUDIT["turns"][5],
              AUDIT["turns"][6]],
}
