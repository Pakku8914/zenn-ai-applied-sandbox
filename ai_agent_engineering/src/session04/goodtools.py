#!/usr/bin/env python3
"""改善版のツール（セッション4の解答）。

badtools.py の4つを、次の5点で直したもの。

  1. 粒度   : 1ツール1責務にする（読み取りと書き込みを混ぜない）
  2. スキーマ: 必須・列挙・範囲・既定値で誤りを構造的に防ぐ
  3. 説明文 : 「いつ使うか」と「いつ使わないか」を書く
  4. エラー : 何が悪かったか＋次に何をすべきかを返す
  5. 結果   : 必要な列だけ・件数つき・続きの示し方つきで返す

agentkit の実装で足りているものはそのまま使う（`search_docs` / `submit_expense`）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import DATA, search_docs, submit_expense  # noqa: E402
from agentkit.tools import Tool, ToolError, ToolRegistry  # noqa: E402
from toolschema import SchemaCheckedRegistry  # noqa: E402

STATUSES = ("all", "submitted", "approved", "rejected")
CATEGORIES = ("交通費", "出張旅費", "接待交際費", "備品")


def _rows(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        raise ToolError(f"{path.name} がありません。`python tools/make_data.py` を実行してください。")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


# ---------------------------------------------------------------------------
# 読み取り専用（副作用なし・冪等）
# ---------------------------------------------------------------------------
def find_expenses(status: str = "all", min_amount: int = 0, limit: int = 5) -> str:
    """経費申請を状態と金額で絞り込んで一覧する。

    返すのは「必要な5列」「金額の大きい順」「件数」「続きの示し方」だけ。
    全件を返さないのは、ツール結果がそのまま会話履歴に積まれるため。
    """
    if status not in STATUSES:
        raise ToolError(
            f"引数 'status' は次のいずれかを指定してください: {', '.join(STATUSES)}"
            f"（受け取った値: {status}）。")
    if not 1 <= limit <= 20:
        raise ToolError("引数 'limit' は 1 以上 20 以下で指定してください。既定は 5 です。")

    rows = [r for r in _rows("expenses")
            if (status == "all" or r["status"] == status) and r["amount"] >= min_amount]
    rows.sort(key=lambda r: (-r["amount"], r["expense_id"]))
    if not rows:
        return (f"該当 0 件（status={status} / min_amount={min_amount}）。"
                "条件を緩めて再検索してください。")

    shown = rows[:limit]
    lines = [f"該当 {len(rows)} 件（表示 {len(shown)} 件）"]
    lines += [f"{r['expense_id']} | {r['employee']} | {r['amount']} | "
              f"{r['category']} | {r['status']}" for r in shown]
    if len(rows) > len(shown):
        lines.append(f"残り {len(rows) - len(shown)} 件は表示していません。"
                     "limit を増やすか status / min_amount で絞り込んでください。")
    return "\n".join(lines)


def is_actionable(message: str) -> bool:
    """エラーメッセージが「モデルが次の行動を決められる」形かを判定する。

    LLM を使わず、文字列の検査だけで決定的に判定する。
      1. 具体的な候補（許容値・項目名・ツール名）が含まれている
      2. 次の行動を促す表現が含まれている
      3. 長すぎない（150文字以内）
    """
    if not message or len(message) > 150:
        return False
    # 1. 具体的な候補が示されている（列挙のコロン、または数値の範囲）
    has_candidate = ": " in message or ("以上" in message and "以下" in message)
    # 2. 次の行動が示されている（依頼の形、または代替手段の提示）
    has_next_action = "してください" in message or "使えるツール" in message
    return has_candidate and has_next_action


def get_policy_v2(topic: str) -> str:
    """規程の条文を返す。見つからないときは指定できる項目を全部返す。"""
    rows = _rows("policies")
    hit = next((r for r in rows if topic in r["topic"]), None)
    if hit is None:
        raise ToolError(
            f"規程 '{topic}' は見つかりません。"
            f"指定できる項目: {', '.join(r['topic'] for r in rows)}。"
            "この中から選び直してください。")
    return f"{hit['topic']}: {hit['rule']}"


# ---------------------------------------------------------------------------
# 書き込み（副作用あり・冪等キーで再送を吸収する）
# ---------------------------------------------------------------------------
def submit_expense_once(employee: str, amount: int, category: str,
                        idempotency_key: str, note: str = "") -> str:
    """経費を申請する。同じ `idempotency_key` なら2回目以降は申請を作らない。

    agentkit の `submit_expense` は冪等でない（2回呼ぶと2件登録される）。
    冪等性は「フラグを立てる」ことではなく「同じ結果になる実装を書く」こと。
    """
    if not idempotency_key:
        raise ToolError(
            "引数 'idempotency_key' が空です。同じ申請の再送を区別できません。"
            "申請ごとに一意な文字列（例: 2026-08-15-EMP-003-68000）を指定してください。")
    for row in _rows("expenses"):
        if row.get("idempotency_key") == idempotency_key:
            return (f"{row['expense_id']} は同じ idempotency_key で既に受け付けています"
                    f"（金額 {row['amount']} 円 / 区分 {row['category']}）。"
                    "追加の申請はしていません。")
    return submit_expense(employee, amount, category, note=note,
                          idempotency_key=idempotency_key)


# ---------------------------------------------------------------------------
# スキーマと説明文
# ---------------------------------------------------------------------------
FIND_EXPENSES_DESC = (
    "経費申請を状態と金額で絞り込んで一覧します（読み取り専用・副作用なし）。"
    "使う場面: 未承認の申請を探す / 5万円以上の申請を数える。"
    "使わない場面: 申請を新しく作る（submit_expense を使う） / "
    "規程の条文を読む（get_policy を使う）。"
    "金額の大きい順に既定 5 件まで返し、超えた分は件数だけを知らせます。"
)
FIND_EXPENSES_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES), "default": "all",
                   "description": "申請の状態。all は絞り込まない"},
        "min_amount": {"type": "integer", "minimum": 0, "maximum": 10_000_000,
                       "default": 0, "description": "この金額（円）以上に絞る"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5,
                  "description": "返す最大件数。既定 5"},
    },
}

POLICY_DESC = (
    "指定した項目の社内規程の条文を返します（読み取り専用）。"
    "使う場面: 金額の基準や期限を確認する。"
    "使わない場面: 手順の詳細を読む（search_docs のほうが向きます）。"
    "項目名は部分一致で引けます。見つからないときは指定できる項目を返します。"
)
POLICY_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string", "maxLength": 40,
                             "description": "規程の項目名（例: 経費精算）"}},
    "required": ["topic"],
}

SEARCH_DESC = (
    "社内文書を全文検索し、該当した文書の本文を返します（読み取り専用）。"
    "使う場面: 手順の詳細が知りたい。"
    "使わない場面: 金額基準だけが必要なとき（get_policy のほうが短く返ります）。"
    "1件が数百文字になるため limit は 1〜3 を推奨します。"
)
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "maxLength": 60, "description": "検索語"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3,
                  "description": "取得件数。既定 3"},
    },
    "required": ["query"],
}

SUBMIT_DESC = (
    "経費を申請します（データが増える副作用あり）。"
    "同じ idempotency_key で2回呼んでも申請は1件しか作られません。"
    "使う場面: 申請者・金額・区分の3つが利用者から示されたとき。"
    "使わない場面: 金額や区分が推測でしかないとき（先に利用者に確認してください）。"
    "1件5万円以上は承認が必要です。"
)
SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "employee": {"type": "string", "maxLength": 20,
                     "description": "申請者の氏名（例: 高橋 涼）"},
        "amount": {"type": "integer", "minimum": 1, "maximum": 1_000_000,
                   "description": "金額（円）。1 円以上 100 万円以下"},
        "category": {"type": "string", "enum": list(CATEGORIES),
                     "description": "経費の区分"},
        "idempotency_key": {"type": "string", "maxLength": 60,
                            "description": "申請ごとに一意なキー。再送を吸収する"},
        "note": {"type": "string", "maxLength": 200, "default": "",
                 "description": "備考。省略可"},
    },
    "required": ["employee", "amount", "category", "idempotency_key"],
}


def _submit_tool(fn, *, idempotent: bool) -> Tool:
    """スキーマと説明文は同じで、実装だけ差し替えられるようにしておく。

    `idempotent` は実装に合わせて渡す。宣言と実装を食い違わせないため
    （食い違った宣言を信じた再試行が二重申請を作る）。
    """
    return Tool("submit_expense", SUBMIT_DESC, SUBMIT_SCHEMA, fn,
                requires_approval=True, idempotent=idempotent, tags=("write",))


def build_good_registry() -> SchemaCheckedRegistry:
    """改善後のレジストリ（読み取り3つ＋書き込み1つ）。"""
    return SchemaCheckedRegistry([
        Tool("find_expenses", FIND_EXPENSES_DESC, FIND_EXPENSES_SCHEMA,
             find_expenses, tags=("read",)),
        Tool("get_policy", POLICY_DESC, POLICY_SCHEMA, get_policy_v2, tags=("read",)),
        Tool("search_docs", SEARCH_DESC, SEARCH_SCHEMA, search_docs, tags=("read",)),
        _submit_tool(submit_expense_once, idempotent=True),
    ])


def build_unchecked_registry() -> ToolRegistry:
    """比較用：スキーマも実装も同じで、**検証しない**だけのレジストリ。"""
    return ToolRegistry([_submit_tool(submit_expense, idempotent=False)])


def build_checked_registry() -> SchemaCheckedRegistry:
    """比較用：同じスキーマ・同じ実装で、呼び出し口だけ検証するレジストリ。"""
    return SchemaCheckedRegistry([_submit_tool(submit_expense, idempotent=False)])


def read_only(reg: ToolRegistry) -> SchemaCheckedRegistry:
    """tags に "read" を持つツールだけの許可リストを作る。

    `ToolRegistry.subset()` は基底クラスのインスタンスを返すため、
    検証層を維持したい場合はここで組み直す。
    """
    tools = []
    for name in reg.names():
        tool = reg.get(name)
        if tool is not None and "read" in tool.tags:
            tools.append(tool)
    return SchemaCheckedRegistry(tools)


def render_tool_spec(reg: ToolRegistry) -> str:
    """レジストリからツール仕様書（Markdown 表）を生成する。

    仕様書を手で書くと必ず実装とずれる。宣言から生成すればずれない。
    """
    lines = ["| ツール | 副作用 | 冪等 | 承認 | 必須の引数 | 列挙で縛る引数 |",
             "| :--- | :--- | :--- | :--- | :--- | :--- |"]
    for name in reg.names():
        tool = reg.get(name)
        if tool is None:
            continue
        enums = [k for k, v in tool.schema.get("properties", {}).items() if "enum" in v]
        lines.append(
            f"| {name} | {'あり' if 'write' in tool.tags else 'なし'} | "
            f"{'はい' if tool.idempotent else 'いいえ'} | "
            f"{'必要' if tool.requires_approval else '不要'} | "
            f"{', '.join(tool.schema.get('required', [])) or '（なし）'} | "
            f"{', '.join(enums) or '（なし）'} |")
    return "\n".join(lines)
