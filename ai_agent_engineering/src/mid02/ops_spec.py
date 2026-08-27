#!/usr/bin/env python3
"""道具立て・静的計画・実行前の検査（成果物②③の土台）。

    python src/mid02/ops_spec.py     # ツール仕様書と計画の検査結果を出力する

この章の道具立ての方針は3つである。

  1. **要らない道具は持たせない**（S12 の最小権限）。`get_employee` と `read_file` は
     この業務に不要なので、許可リストに入れない。持っていない道具は誤用できない。
  2. **冪等にできるものは実装で冪等にする**（S11）。予約は条件付き更新（`book_room_if_free`）、
     申請は冪等キー（`submit_expense_once`）。残るのは送信だけである。
  3. **副作用の引数は計画が決める**。モデルが埋めてよい引数を計画が `alterable` で宣言する。
     金額・宛先・冪等キーはこの宣言に入れない（入れた計画は実行前の検査で落とす）。

比較用に「防御を外した道具立て」も同じ関数から作れるようにしてある。守れていることを
示すには、守っていない構成での再現が必要である（S12）。
"""

from __future__ import annotations

from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from agentkit.biztools import (book_room, get_employee, read_file,  # noqa: E402
                               search_docs, send_message, submit_expense, write_file)
from agentkit.models import ToolCall  # noqa: E402
from agentkit.tools import Tool  # noqa: E402
from boundary import classify_source  # noqa: E402  (S12)
from defenses import (ExactRecipientInspector, InspectedRegistry,  # noqa: E402
                      UntrustedResultRegistry)
from ex_content_guard import ContentInspector  # noqa: E402  (S12 の練習問題の解)
from faults import flaky_tool  # noqa: E402  (S11)
from goodtools import (FIND_EXPENSES_DESC, FIND_EXPENSES_SCHEMA,  # noqa: E402
                       POLICY_DESC, POLICY_SCHEMA, SEARCH_DESC, SEARCH_SCHEMA,
                       SUBMIT_DESC, SUBMIT_SCHEMA, find_expenses, get_policy_v2,
                       submit_expense_once)
from idempotency import book_room_if_free, expense_key  # noqa: E402  (S11)
from policy import (MATRIX, MODE_LABEL, MODES, OPERATIONS, THRESHOLD_YEN,  # noqa: E402
                     decide)
from toolschema import SchemaCheckedRegistry  # noqa: E402  (S04)

from flow import REQUIRED_SOURCES, STATE_TOOLS  # noqa: E402
from ledger import can_match  # noqa: E402

# この業務に必要な道具だけ。get_employee と read_file は入れない
TASK_ALLOW_OPS = ("find_expenses", "get_policy", "search_docs",
                  "book_room", "submit_expense", "send_message", "write_file")

# 読み取り専用の道具（段階の判定にかけない）
READ_ONLY = ("find_expenses", "get_policy", "search_docs", "get_employee", "read_file")

# 打ち消し方の宣言。ここに無い操作は**打ち消せない**
UNDO_BY_TOOL = {"submit_expense": "cancel_expense", "book_room": "cancel_booking"}

# モデルに変えさせてはいけない引数（計画の alterable に入っていたら実行前に落とす）
FORBIDDEN_ALTERABLE = ("amount", "to", "employee", "category", "idempotency_key", "path")

# ---------------------------------------------------------------------------
# スキーマと説明文（S04 にあるものは再利用し、無いものだけここで書く）
# ---------------------------------------------------------------------------
BOOK_DESC = (
    "会議室を予約します（他人の予定表に出る副作用あり）。"
    "使う場面: 開催日時と部屋が決まっている。"
    "使わない場面: 空き枠を調べる（この道具は調べるためのものではありません）。"
    "同じ日・同じ部屋・同じ開始時刻の予約が既にあれば、新しく作りません（冪等）。"
)
BOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "room": {"type": "string", "maxLength": 20, "description": "会議室名（例: みなと）"},
        "start": {"type": "string", "maxLength": 5, "description": "開始時刻（HH:MM）"},
        "minutes": {"type": "integer", "minimum": 15, "maximum": 240, "default": 60,
                    "description": "利用時間（分）。既定 60"},
    },
    "required": ["room", "start"],
}

SEND_DESC = (
    "社内チャットへメッセージを送信します（**取り消せない**副作用あり）。"
    "使う場面: 決まったことを関係者へ知らせる。"
    "使わない場面: 相談・確認（送信は取り消せないので、下書きを人に見せてください）。"
    "宛先は社員ID（EMP-000 形式）とチャンネル（#general / #ops）だけです。"
)
SEND_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "maxLength": 60, "description": "宛先（EMP-000 / #ops）"},
        "body": {"type": "string", "maxLength": 2000, "description": "本文"},
    },
    "required": ["to", "body"],
}

WRITE_DESC = (
    "作業領域にファイルを書きます（データが増える副作用あり）。"
    "使う場面: 実行報告・引き継ぎ書を保存する。"
    "使わない場面: 途中の思考を書き留める（進捗は状態が持つので不要です）。"
    "同じパスに同じ内容を書けば結果は同じです（冪等）。"
)
WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "maxLength": 80,
                 "description": "workspace/ からの相対パス（例: mid02/report.md）"},
        "content": {"type": "string", "maxLength": 8000, "description": "書き込む本文"},
    },
    "required": ["path", "content"],
}

EMPLOYEE_DESC = (
    "社員情報を返します（この業務では使いません）。"
    "比較用の道具立てにだけ登録します。"
)
EMPLOYEE_SCHEMA = {
    "type": "object",
    "properties": {"employee_id": {"type": "string", "maxLength": 10}},
    "required": ["employee_id"],
}

READ_FILE_DESC = "作業領域のファイルを読みます（この業務では使いません）。"
READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string", "maxLength": 80}},
    "required": ["path"],
}


# ---------------------------------------------------------------------------
# 静的計画（副作用の列）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OpsStep:
    """1つの副作用と、その扱い方の宣言。

    args      … 状態が確定させる引数（モデルの提案では上書きされない）
    alterable … モデルが埋めてよい引数の名前（ホワイトリスト）
    undo      … 打ち消し方（空文字列＝打ち消せない）
    needs     … 実行前にそろっている必要がある材料
    """

    id: str
    tool: str
    intent: str
    args: dict
    alterable: tuple[str, ...] = ()
    undo: str = ""
    needs: tuple[str, ...] = ()


NOTIFY_BODY = "部門報告会の準備が整いました。開始時刻と会議室は追って確定します。"

OPS_PLAN: tuple[OpsStep, ...] = (
    OpsStep("sg_room", "book_room", "報告会の会議室を1時間押さえる",
            {"room": "みなと", "start": "10:00", "minutes": 60},
            alterable=("room", "start"), undo="cancel_booking",
            needs=("get_policy",)),
    OpsStep("sg_expense", "submit_expense", "懇親会費を申請する",
            {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
             "note": "部門報告会の懇親会費",
             "idempotency_key": expense_key("EMP-003", 68_000)},
            alterable=("note",), undo="cancel_expense",
            needs=("get_policy", "find_expenses")),
    OpsStep("sg_notify", "send_message", "参加者へ連絡する",
            {"to": "#ops", "body": NOTIFY_BODY},
            alterable=("body",), undo="",
            needs=("get_policy",)),
)

# 実行前の検査に落ちる計画（比較用）
PLAN_LOOSE = (
    OPS_PLAN[0],
    OpsStep("sg_expense", "submit_expense", "懇親会費を申請する",
            dict(OPS_PLAN[1].args), alterable=("note", "amount"),
            undo="cancel_expense", needs=("get_policy", "find_expenses")),
    OPS_PLAN[2],
)
PLAN_UNREGISTERED = (
    OpsStep("sg_leak", "get_employee", "社員情報を取る", {"employee_id": "EMP-001"},
            undo="", needs=()),
    *OPS_PLAN,
)


# ---------------------------------------------------------------------------
# レジストリ
# ---------------------------------------------------------------------------
def _tool(name: str, *, submit: str, book: str):
    """1つの道具を作る。宣言（冪等・承認）は必ず実装に合わせる。"""
    if name == "find_expenses":
        return Tool(name, FIND_EXPENSES_DESC, FIND_EXPENSES_SCHEMA, find_expenses,
                    tags=("read",))
    if name == "get_policy":
        return Tool(name, POLICY_DESC, POLICY_SCHEMA, get_policy_v2, tags=("read",))
    if name == "search_docs":
        return Tool(name, SEARCH_DESC, SEARCH_SCHEMA, search_docs, tags=("read",))
    if name == "book_room":
        conditional = book == "conditional"
        return Tool(name, BOOK_DESC, BOOK_SCHEMA,
                    book_room_if_free if conditional else book_room,
                    idempotent=conditional, tags=("write",))
    if name == "submit_expense":
        idempotent = submit == "idempotent"
        return Tool(name, SUBMIT_DESC, SUBMIT_SCHEMA,
                    submit_expense_once if idempotent else submit_expense,
                    requires_approval=True, idempotent=idempotent, tags=("write",))
    if name == "send_message":
        return Tool(name, SEND_DESC, SEND_SCHEMA, send_message,
                    requires_approval=True, idempotent=False, tags=("write", "external"))
    if name == "write_file":
        return Tool(name, WRITE_DESC, WRITE_SCHEMA, write_file, idempotent=True,
                    tags=("write",))
    if name == "get_employee":
        return Tool(name, EMPLOYEE_DESC, EMPLOYEE_SCHEMA,
                    lambda employee_id: get_employee(employee_id, "manager"),
                    tags=("read",))
    if name == "read_file":
        return Tool(name, READ_FILE_DESC, READ_FILE_SCHEMA, read_file, tags=("read",))
    raise ValueError(f"未知のツールです: {name}")


def build_registry(*, restrict: bool = True, submit: str = "idempotent",
                   book: str = "conditional", faults: tuple = ()) -> SchemaCheckedRegistry:
    """道具立てを作る。

    restrict=False は比較用（この業務に要らない `get_employee` と `read_file` も持たせ、
    社員情報は manager 権限で返る）。faults は ((ツール名, when, メッセージ), ...) の形で
    障害を注入する（S11 の `flaky_tool`）。
    """
    names = list(TASK_ALLOW_OPS)
    if not restrict:
        names += ["get_employee", "read_file"]
    tools = [_tool(name, submit=submit, book=book) for name in names]
    injected = {name: (when, message) for name, when, message in faults}
    tools = [flaky_tool(t, fail_on=(1,), when=injected[t.name][0],
                        message=injected[t.name][1]) if t.name in injected else t
             for t in tools]
    return SchemaCheckedRegistry(tools)


INSPECTORS = {"none": None, "recipient": ExactRecipientInspector, "content": ContentInspector}


def build_tools(*, restrict: bool = True, inspect: str = "content",
                separate: bool = True, submit: str = "idempotent",
                book: str = "conditional", faults: tuple = ()):
    """防御の層を巻いたレジストリを返す（内側から順に巻く）。

    戻り値は (レジストリ, 警告のリスト, 遮断のリスト)。数えるためにリストを外へ出す。
    """
    reg = build_registry(restrict=restrict, submit=submit, book=book, faults=faults)
    alerts: list = []
    blocked: list = []
    if separate:
        reg = UntrustedResultRegistry(reg, detect=True, separate=True, alerts=alerts)
    factory = INSPECTORS[inspect]
    if factory is not None:
        reg = InspectedRegistry(reg, factory(), blocked=blocked)
    return reg, alerts, blocked


# ---------------------------------------------------------------------------
# 実行前の検査
# ---------------------------------------------------------------------------
def default_mode(name: str) -> str:
    """可逆性×影響範囲だけで決まる既定の段階（引数を見ない粗い判定）。"""
    op = OPERATIONS.get(name)
    if op is None:
        return "approve"   # 分類されていない操作は止める側に倒す（S10）
    return MATRIX[(op.reversibility, op.blast)]


def plan_mode(step: OpsStep, registry) -> str:
    """計画に書かれた引数まで見た段階（S10 の `decide`）。"""
    return decide(ToolCall(f"plan-{step.id}", step.tool, dict(step.args)),
                  registry.get(step.tool), threshold_yen=THRESHOLD_YEN).mode


def check_plan(plan, registry) -> list[str]:
    """計画を実行前に検査する。1件でも違反があればモデルを1回も呼ばない。

    検査するのは「この計画が壊れないか」だけである。うまくいくかは検査できない。
    """
    violations: list[str] = []
    for step in plan:
        tool = registry.get(step.tool)
        if tool is None:
            violations.append(
                f"操作 '{step.id}': 未登録のツール '{step.tool}' を使っています。"
                f"許可リスト: {', '.join(registry.names())}。")
            continue
        if step.tool not in STATE_TOOLS["executing"]:
            violations.append(
                f"操作 '{step.id}': ツール '{step.tool}' は executing の許可リストにありません。")
        bad = [key for key in step.alterable if key in FORBIDDEN_ALTERABLE]
        if bad:
            violations.append(
                f"操作 '{step.id}': モデルに変えさせてはいけない引数が alterable にあります: "
                f"{', '.join(bad)}。金額・宛先・冪等キーは状態が確定させてください。")
        unknown = [key for key in step.alterable if key not in step.args]
        if unknown:
            violations.append(
                f"操作 '{step.id}': alterable に計画外の引数があります: {', '.join(unknown)}。")
        mode = plan_mode(step, registry)
        if not step.undo and MODES.index(mode) < MODES.index("approve"):
            violations.append(
                f"操作 '{step.id}': 打ち消せない操作なのに段階が {MODE_LABEL[mode]} です。"
                "事前承認以上にしてください。")
        if tool.idempotent and not can_match(step.tool):
            violations.append(
                f"操作 '{step.id}': 冪等と宣言していますが、実行済みかを照合する手段が"
                "ありません（`ledger.MATCHERS` に無い）。")
        outside = [name for name in step.needs if name not in REQUIRED_SOURCES]
        if outside:
            violations.append(
                f"操作 '{step.id}': 材料 {', '.join(outside)} は読み取りでそろいません。")
    return violations


def check_runner_config(*, retry_mode: str, registry) -> list[str]:
    """実行器の設定を実行前に検査する（練習問題で足す層）。

    「判断なしの再試行」は、冪等でない書き込みを持つ道具立てと組み合わせた時点で
    二重実行が確定する。結果を見て気づくのではなく、始める前に落とせる。
    """
    if retry_mode != "blind":
        return []
    risky = [name for name in registry.names()
             if (tool := registry.get(name)) is not None
             and "write" in tool.tags and not tool.idempotent]
    return ["判断なしの再試行（blind）は、冪等でない書き込みを二重実行します: "
            + (", ".join(risky) if risky else "（該当なし）")]


# ---------------------------------------------------------------------------
# ツール仕様書（成果物②）。宣言から生成するので実装とずれない
# ---------------------------------------------------------------------------
def render_spec_md(registry=None) -> str:
    registry = registry or build_registry()
    plan_tools = {step.tool: step for step in OPS_PLAN}
    lines = ["| ツール | 出所 | 副作用 | 冪等 | 照合 | 既定の段階 | 打ち消し | 使える状態 |",
             "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for name in registry.names():
        tool = registry.get(name)
        if tool is None:
            continue
        states = [state for state, allowed in STATE_TOOLS.items() if name in allowed]
        if name in READ_ONLY:
            mode = "—（読み取り）"
        else:
            step = plan_tools.get(name)
            mode = MODE_LABEL[plan_mode(step, registry) if step else default_mode(name)]
        lines.append(
            f"| {name} | {classify_source(name)} | "
            f"{'あり' if 'write' in tool.tags else 'なし'} | "
            f"{'はい' if tool.idempotent else 'いいえ'} | "
            f"{'できる' if can_match(name) else 'できない'} | {mode} | "
            f"{UNDO_BY_TOOL.get(name, '打ち消せない') if 'write' in tool.tags else '—'} | "
            f"{', '.join(states) or '（なし）'} |")
    return "\n".join(lines)


def render_plan_md(registry=None) -> str:
    registry = registry or build_registry()
    lines = ["| 操作 | ツール | 段階 | 状態が決める引数 | モデルが埋めてよい引数 | 打ち消し |",
             "| :--- | :--- | :--- | :--- | :--- | :--- |"]
    for step in OPS_PLAN:
        fixed = [key for key in sorted(step.args) if key not in step.alterable]
        lines.append(
            f"| {step.id} | {step.tool} | {MODE_LABEL[plan_mode(step, registry)]} | "
            f"{', '.join(fixed)} | {', '.join(step.alterable) or '（なし）'} | "
            f"{step.undo or '打ち消せない'} |")
    return "\n".join(lines)


def main() -> None:
    registry = build_registry()
    print("=== ツール仕様書（成果物②） ===")
    print(render_spec_md(registry))
    print("\n=== 静的計画（副作用の列） ===")
    print(render_plan_md(registry))
    print("\n=== 実行前の検査 ===")
    print(f"OPS_PLAN の違反: {check_plan(OPS_PLAN, registry) or 'なし'}")
    for label, plan in (("PLAN_LOOSE", PLAN_LOOSE), ("PLAN_UNREGISTERED", PLAN_UNREGISTERED)):
        for violation in check_plan(plan, registry):
            print(f"{label}: {violation}")
    print(f"\n実行器の設定（blind）: {check_runner_config(retry_mode='blind', registry=registry)}")


if __name__ == "__main__":
    main()
