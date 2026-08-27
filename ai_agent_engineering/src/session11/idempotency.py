#!/usr/bin/env python3
"""冪等化の3手法（セッション11）。

  A 冪等キー     … 受け取る側が「同じキーなら1回しか作らない」を保証する
  B 条件付き更新 … 受け取る側が「その状態でなければ書かない」を1操作で行う
  C 事前確認     … 呼ぶ側が先に一覧を引いて重複を探す（隙間が呼ぶ側に残る）

A の実装はセッション4の `submit_expense_once` をそのまま使う。冪等キーの形も
セッション4の規約どおり `日付-社員ID-金額` である（この章で作り直さない）。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
S04 = ROOT / "src" / "session04"
for _p in (str(ROOT), str(HERE), str(S04)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import (DATA, book_room, build_registry,  # noqa: E402
                               submit_expense)
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.tools import Tool, ToolRegistry  # noqa: E402
from faults import flaky_tool  # noqa: E402
from goodtools import SUBMIT_SCHEMA, submit_expense_once  # noqa: E402

CANCELLED = "cancelled"


def expense_key(employee_id: str, amount: int, date: str = "2026-08-15") -> str:
    """セッション4の冪等キー（日付-社員ID-金額）。

    同じ意図の申請なら**同じ値**になってほしい鍵である。
    セッション10の照合ハッシュ（1文字違えば別の値になってほしい鍵）とは目的が逆。
    """
    return f"{date}-{employee_id}-{amount}"


# --- データ側で数える（軌跡ではなく副作用そのものを数える）------------------
def rows(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def count_rows(name: str) -> int:
    return len(rows(name))


def active_expenses() -> int:
    """取り消されていない申請の件数。補償の結果を数えるのに使う。"""
    return sum(1 for r in rows("expenses") if r.get("status") != CANCELLED)


# --- 手法A：冪等キー --------------------------------------------------------
SUBMIT_DESC = ("経費を申請します（データが増える副作用あり）。"
               "同じ idempotency_key で2回呼んでも申請は1件しか作られません。")


def build_submit_registry(*, idempotent: bool, fail_on: tuple[int, ...] = (1,),
                          when: str = "after") -> ToolRegistry:
    """`submit_expense` だけを持つレジストリ。実装だけを差し替える。

    宣言（`idempotent`）は実装に合わせる。食い違わせると、その宣言を信じた
    再試行が二重申請を作る（セッション4の `_submit_tool` と同じ考え方）。
    """
    return ToolRegistry([_flaky_submit(idempotent, fail_on, when)])


def _flaky_submit(idempotent: bool, fail_on: tuple[int, ...], when: str) -> Tool:
    fn = submit_expense_once if idempotent else submit_expense
    tool = Tool("submit_expense", SUBMIT_DESC, SUBMIT_SCHEMA, fn,
                requires_approval=True, idempotent=idempotent, tags=("write",))
    return flaky_tool(tool, fail_on=fail_on, when=when)


def build_registry_with_flaky_submit(*, idempotent: bool,
                                     fail_on: tuple[int, ...] = (1,),
                                     when: str = "after") -> ToolRegistry:
    """業務ツール一式のうち、`submit_expense` だけを失敗する版に差し替える。"""
    base = build_registry()
    tools = [base.get(n) for n in base.names() if n != "submit_expense"]
    tools.append(_flaky_submit(idempotent, fail_on, when))
    return ToolRegistry([t for t in tools if t is not None])


# --- 手法B：条件付き更新 ----------------------------------------------------
def book_room_if_free(room: str, start: str, minutes: int = 60) -> str:
    """同じ日・同じ部屋・同じ開始時刻の予約が既にあれば、新しく作らない。

    キーを外から渡さなくてよいのが利点。「その枠が空いている」という**条件**
    そのものが一意性を与えるためである。逆に「増やす」操作（申請の追加）には
    使えない。同じ内容の申請が2件あってよい業務では、条件を書きようがない。
    """
    today = FixedClock().today()
    for r in rows("bookings"):
        if r.get("room") == room and r.get("start") == start and r.get("date") == today:
            return f"{room} の {start} は既に予約済みです（重複予約を作りませんでした）。"
    return book_room(room, start, minutes)


# --- 手法C：事前確認 --------------------------------------------------------
def submit_after_precheck(employee: str, amount: int, category: str,
                          idempotency_key: str, note: str = "",
                          interleave: Callable[[], None] | None = None) -> str:
    """呼ぶ側が先に一覧を引いて重複を探してから申請する。

    `interleave` は「確認と実行の間に他の実行者が割り込む」ことを決定的に
    再現するための穴である（本番のコードにこの引数は無い）。
    """
    for r in rows("expenses"):
        if r.get("idempotency_key") == idempotency_key:
            return f"{r['expense_id']} は既に申請済みです（事前確認で見つけました）。"
    if interleave is not None:
        interleave()   # ← ここが隙間。呼ぶ側にはこの隙間を閉じる手段がない
    return submit_expense(employee, amount, category, note=note,
                          idempotency_key=idempotency_key)


METHODS = ("冪等キー", "条件付き更新", "事前確認")


if __name__ == "__main__":
    import subprocess

    def reset() -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                       check=True, capture_output=True)

    key = expense_key("EMP-003", 68_000)

    reset()
    before = count_rows("expenses")
    submit_expense_once("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
    submit_expense_once("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
    print(f"A 冪等キー      : 2回呼んで {count_rows('expenses') - before} 件")

    reset()
    before = count_rows("bookings")
    book_room_if_free("うみかぜ", "10:00")
    book_room_if_free("うみかぜ", "10:00")
    print(f"B 条件付き更新  : 2回呼んで {count_rows('bookings') - before} 件")

    reset()
    before = count_rows("expenses")
    submit_after_precheck(
        "高橋 涼", 68_000, "接待交際費", idempotency_key=key,
        interleave=lambda: submit_expense("高橋 涼", 68_000, "接待交際費",
                                          idempotency_key=key))
    print(f"C 事前確認      : 割り込みが入ると {count_rows('expenses') - before} 件")
    reset()
