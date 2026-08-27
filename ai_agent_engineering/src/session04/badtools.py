#!/usr/bin/env python3
"""意図的に悪く作ったツール（セッション4の「直す前」）。

このファイルは**直さない**。改善版は goodtools.py に別の名前で書く。
悪さは4種類に分けてある。

  1. manage_expense      : 引数が自由文字列1つ（何でもできると称する）
  2. expense_report_raw  : 例外を Traceback のまま「成功」として返す
  3. dump_expenses       : 全件・全項目を JSON で返す
  4. policy_lookup       : 失敗したときに次の行動の手がかりを返さない
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import DATA, submit_expense  # noqa: E402
from agentkit.tools import Tool, ToolError, ToolRegistry  # noqa: E402


def _rows(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        raise ToolError(f"{path.name} がありません。`python tools/make_data.py` を実行してください。")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


# ---------------------------------------------------------------------------
# 悪い例1：引数が自由文字列1つ
# ---------------------------------------------------------------------------
def manage_expense(instruction: str) -> str:
    """経費に関する操作をまとめて行う（と称する）ツール。

    内部では「申請|一覧|取消 <氏名> <金額> <区分>」という空白区切りの並びを
    期待している。その形式は description にもスキーマにも書いていない。
    形式が違うと「処理できませんでした。」だけが返る。
    """
    parts = instruction.split()
    if len(parts) != 4 or parts[0] not in ("申請", "一覧", "取消"):
        raise ToolError("処理できませんでした。")
    if not parts[2].isdigit():
        raise ToolError("処理できませんでした。")
    if parts[0] != "申請":
        raise ToolError("処理できませんでした。")
    # ここに到達すると、確認なしで副作用のある操作が走る（自由文字列の怖さ）
    return submit_expense(parts[1], int(parts[2]), parts[3])


# ---------------------------------------------------------------------------
# 悪い例2：Traceback をそのまま、しかも「成功」として返す
# ---------------------------------------------------------------------------
def expense_report_raw(query: str) -> str:
    """月を指定して経費データを返す（つもりの）ツール。"""
    try:
        month = int(query)  # "8月" のような自然な入力で ValueError になる
        rows = [r for r in _rows("expenses") if r["created_at"][5:7] == f"{month:02d}"]
        return json.dumps(rows, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        # 例外を握りつぶし、Traceback を戻り値として返している。
        # ToolRegistry から見れば ok=True。つまり**失敗が成功に化ける**
        return traceback.format_exc()


# ---------------------------------------------------------------------------
# 悪い例3：全件・全項目を JSON で返す
# ---------------------------------------------------------------------------
def dump_expenses() -> str:
    """経費データを返す。絞り込みは呼び出し側（モデル）任せ。"""
    return json.dumps(_rows("expenses"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 悪い例4：失敗しても次の行動が決まらないエラー
# ---------------------------------------------------------------------------
def policy_lookup(topic: str) -> str:
    """規程を引く。見つからないときの手がかりが無い。"""
    for row in _rows("policies"):
        if topic in row["topic"]:
            return row["rule"]
    raise ToolError("not found")


def build_bad_registry() -> ToolRegistry:
    """悪いツールだけを載せたレジストリ（スキーマもわざと緩い）。"""
    return ToolRegistry([
        Tool("manage_expense",
             "経費に関する操作をまとめて行います。",
             {"type": "object",
              "properties": {"instruction": {"type": "string"}},
              "required": ["instruction"]},
             manage_expense, tags=("write",)),
        Tool("expense_report_raw",
             "経費のレポート用データを返します。",
             {"type": "object",
              "properties": {"query": {"type": "string"}},
              "required": ["query"]},
             expense_report_raw, tags=("read",)),
        Tool("dump_expenses",
             "経費データを返します。",
             {"type": "object", "properties": {}},
             dump_expenses, tags=("read",)),
        Tool("policy_lookup",
             "規程を引きます。",
             {"type": "object",
              "properties": {"topic": {"type": "string"}},
              "required": ["topic"]},
             policy_lookup, tags=("read",)),
    ])
