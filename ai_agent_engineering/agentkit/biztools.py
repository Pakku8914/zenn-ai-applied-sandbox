"""みなと商事の業務ツール群（全章で使い回す）。

意図的に残している「実務の厄介さ」（requirements.md 参照）:
  - `submit_expense` は冪等でない（同じ内容を2回呼ぶと二重申請になる）
  - `book_room` は特定の時間帯で必ず競合エラーを返す
  - `search_docs` の結果に間接プロンプトインジェクションが混ざる
  - `get_employee` は役職によって見せてよい項目が違う
"""

from __future__ import annotations

import json
from pathlib import Path

from .clock import FixedClock
from .tools import Tool, ToolError

DATA = Path(__file__).resolve().parent.parent / "data"
WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"

# 予約が必ず競合する時間帯（決定的に失敗させるため。乱数を使わない）
CONFLICT_SLOTS = {("みなと", "10:00"), ("大会議室", "13:00")}


def _load(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        raise ToolError(
            f"{path.name} がありません。`python tools/make_data.py` を実行してください。"
        )
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _append(name: str, row: dict) -> None:
    path = DATA / f"{name}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 読み取り系（副作用なし・冪等）
# ---------------------------------------------------------------------------
def search_docs(query: str, limit: int = 3) -> str:
    """社内文書を検索する。語の一致で並べる素朴な実装。"""
    docs = _load("docs")
    scored = [(sum(1 for ch in set(query) if ch in d["title"] + d["body"]), d) for d in docs]
    scored.sort(key=lambda t: (-t[0], t[1]["doc_id"]))
    hits = [d for score, d in scored[:limit] if score > 0]
    if not hits:
        return "該当する文書は見つかりませんでした。"
    return "\n\n".join(f"[{d['doc_id']}] {d['title']}\n{d['body']}" for d in hits)


def list_expenses(status: str = "all") -> str:
    rows = _load("expenses")
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    if not rows:
        return "該当する申請はありません。"
    header = "expense_id | 申請者 | 金額 | 区分 | 状態 | 起票日"
    lines = [f"{r['expense_id']} | {r['employee']} | {r['amount']} | {r['category']} | "
             f"{r['status']} | {r['created_at']}" for r in rows]
    return "\n".join([header, *lines])


def get_policy(topic: str) -> str:
    rows = _load("policies")
    for r in rows:
        if topic in r["topic"]:
            return f"{r['topic']}: {r['rule']}"
    available = ", ".join(r["topic"] for r in rows)
    raise ToolError(f"'{topic}' の規程は見つかりません。指定できる項目: {available}")


def get_employee(employee_id: str, requester_role: str = "member") -> str:
    """社員情報を引く。役職によって返す項目を変える（権限は取得側で絞る）。"""
    rows = _load("employees")
    row = next((r for r in rows if r["employee_id"] == employee_id), None)
    if row is None:
        raise ToolError(f"社員 {employee_id} は存在しません。employee_id を確認してください。")
    public = {"employee_id": row["employee_id"], "name": row["name"],
              "dept": row["dept"], "role": row["role"]}
    if requester_role != "manager":
        return json.dumps(public, ensure_ascii=False)
    return json.dumps({**public, "address": row["address"],
                       "evaluation": row["evaluation"]}, ensure_ascii=False)


def read_file(path: str) -> str:
    """作業領域のファイルを読む。作業領域の外は読めない。"""
    target = (WORKSPACE / path).resolve()
    if not str(target).startswith(str(WORKSPACE.resolve())):
        raise ToolError("作業領域（workspace/）の外は読めません。相対パスで指定してください。")
    if not target.exists():
        raise ToolError(f"{path} は存在しません。先に write_file で作成してください。")
    return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 書き込み系（副作用あり）
# ---------------------------------------------------------------------------
def write_file(path: str, content: str) -> str:
    target = (WORKSPACE / path).resolve()
    if not str(target).startswith(str(WORKSPACE.resolve())):
        raise ToolError("作業領域（workspace/）の外には書けません。相対パスで指定してください。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"{path} に {len(content)} 文字を書き込みました。"


def submit_expense(employee: str, amount: int, category: str, note: str = "",
                   idempotency_key: str = "") -> str:
    """経費を申請する。

    **冪等ではない**（同じ内容で2回呼ぶと2件登録される）。
    セッション11で読者が `idempotency_key` を使って冪等化する。
    引数は最初から用意してあるが、既定の実装では**使っていない**。
    """
    rows = _load("expenses")
    new_id = f"EXP-{len(rows) + 1:04d}"
    _append("expenses", {"expense_id": new_id, "employee": employee, "amount": amount,
                         "category": category, "status": "submitted", "note": note,
                         "created_at": FixedClock().today(),
                         "idempotency_key": idempotency_key})
    return f"{new_id} を申請しました（金額 {amount} 円 / 区分 {category}）。"


def book_room(room: str, start: str, minutes: int = 60) -> str:
    """会議室を予約する。特定の枠は必ず競合する（決定的に失敗させるため）。"""
    rooms = {r["room"] for r in _load("rooms")}
    if room not in rooms:
        raise ToolError(f"会議室 '{room}' は存在しません。指定できる会議室: {', '.join(sorted(rooms))}")
    if (room, start) in CONFLICT_SLOTS:
        raise ToolError(
            f"{room} の {start} は既に予約されています。"
            "別の時間帯（例: 11:00）または別の会議室を指定してください。"
        )
    if minutes > 240:
        raise ToolError("連続利用は4時間（240分）までです。分割して予約してください。")
    _append("bookings", {"room": room, "start": start, "minutes": minutes,
                         "date": FixedClock().today()})
    return f"{room} を {start} から {minutes} 分予約しました。"


def send_message(to: str, body: str) -> str:
    """社内チャットへ送信する。取り返しがつかないので承認対象にする。"""
    _append("messages", {"to": to, "body": body, "sent_at": FixedClock().now().isoformat()})
    return f"{to} へメッセージを送信しました（{len(body)} 文字）。"


# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------
def build_registry(requester_role: str = "member"):
    """業務ツールを登録したレジストリを返す。"""
    from .tools import ToolRegistry

    return ToolRegistry([
        Tool("search_docs",
             "社内文書を検索し、該当する文書の本文を返します。規程や手順を調べるときに使います。",
             {"type": "object",
              "properties": {"query": {"type": "string", "description": "検索語"},
                             "limit": {"type": "integer", "description": "取得件数（既定3）"}},
              "required": ["query"]},
             search_docs, tags=("read",)),
        Tool("get_policy",
             "指定した項目の社内規程の本文を返します。金額基準や期限を確認するときに使います。",
             {"type": "object",
              "properties": {"topic": {"type": "string", "description": "規程の項目名"}},
              "required": ["topic"]},
             get_policy, tags=("read",)),
        Tool("list_expenses",
             "経費申請の一覧を返します。status で絞り込めます（all / submitted / approved / rejected）。",
             {"type": "object",
              "properties": {"status": {"type": "string",
                                        "enum": ["all", "submitted", "approved", "rejected"]}}},
             list_expenses, tags=("read",)),
        Tool("get_employee",
             "社員情報を返します。役職によって返される項目が異なります。",
             {"type": "object",
              "properties": {"employee_id": {"type": "string"}},
              "required": ["employee_id"]},
             lambda employee_id: get_employee(employee_id, requester_role), tags=("read",)),
        Tool("read_file",
             "作業領域のファイルを読みます。作業領域の外は読めません。",
             {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
             read_file, tags=("read",)),
        Tool("write_file",
             "作業領域にファイルを書きます。レポートの下書きなどに使います。",
             {"type": "object",
              "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
              "required": ["path", "content"]},
             write_file, idempotent=True, tags=("write",)),
        Tool("submit_expense",
             "経費を申請します。金額が5万円以上の場合は承認が必要です。",
             {"type": "object",
              "properties": {"employee": {"type": "string"},
                             "amount": {"type": "integer", "description": "金額（円）"},
                             "category": {"type": "string",
                                          "enum": ["交通費", "出張旅費", "接待交際費", "備品"]},
                             "note": {"type": "string"},
                             "idempotency_key": {"type": "string",
                                                 "description": "同一申請の再送を吸収するキー"}},
              "required": ["employee", "amount", "category"]},
             submit_expense, requires_approval=True, idempotent=False, tags=("write",)),
        Tool("book_room",
             "会議室を予約します。連続利用は4時間までです。",
             {"type": "object",
              "properties": {"room": {"type": "string"},
                             "start": {"type": "string", "description": "開始時刻（HH:MM）"},
                             "minutes": {"type": "integer"}},
              "required": ["room", "start"]},
             book_room, idempotent=False, tags=("write",)),
        Tool("send_message",
             "社内チャットへメッセージを送信します。送信は取り消せません。",
             {"type": "object",
              "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
              "required": ["to", "body"]},
             send_message, requires_approval=True, idempotent=False, tags=("write", "external")),
    ])
