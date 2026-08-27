#!/usr/bin/env python3
"""補償（部分的に進んだ処理を打ち消す）。セッション11。

エージェントの仕事は「複数の副作用を順に出す」形になりがちである。
3つ目で失敗したとき、1つ目と2つ目は残っている。取り消せる形にしておかないと、
中途半端な状態が業務データに積もっていく。

要点は3つ。

  1. 打ち消しは**逆順**に行う（後から出した副作用が先に消える）
  2. 打ち消しそのものも**冪等**にする（補償が失敗して再試行されるため）
  3. 打ち消しの形は業務が決める（枠は解放する／申請は取り消し記録を残す）
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402
from idempotency import CANCELLED, rows  # noqa: E402


# --- 打ち消しの実装 ---------------------------------------------------------
def cancel_expense_by_key(key: str) -> str:
    """冪等キーで申請を打ち消す。行は消さず status を cancelled にする。

    経費は「無かったことにする」わけにいかない。誰がいつ取り消したかが
    追えなくなるためである。**打ち消しは記録を足す操作**として実装する。
    """
    if not key:
        raise ToolError("idempotency_key が空です。何を打ち消すのか特定できません。")
    path = DATA / "expenses.jsonl"
    current = rows("expenses")
    targets = [r for r in current
               if r.get("idempotency_key") == key and r.get("status") != CANCELLED]
    if not targets:
        return f"打ち消す申請はありません（key={key}）。"
    for r in current:
        if r.get("idempotency_key") == key and r.get("status") != CANCELLED:
            r["status"] = CANCELLED
            r["note"] = f"{r.get('note', '')}（補償により取り消し）"
    with path.open("w", encoding="utf-8") as f:
        for r in current:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ids = ", ".join(r["expense_id"] for r in targets)
    return f"{ids} を取り消しました（{len(targets)} 件・行は残します）。"


def cancel_booking(room: str, start: str) -> str:
    """予約を打ち消す。枠は解放しないと意味がないので行を消す。"""
    path = DATA / "bookings.jsonl"
    today = FixedClock().today()
    current = rows("bookings")
    keep = [r for r in current
            if not (r.get("room") == room and r.get("start") == start
                    and r.get("date") == today)]
    removed = len(current) - len(keep)
    with path.open("w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return f"{room} の {start} の予約を {removed} 件取り消しました。"


# --- サガ（順に実行し、失敗したら逆順に打ち消す）----------------------------
@dataclass
class Action:
    """1つの操作と、その打ち消し方。"""

    name: str
    do: Callable[[], str]
    undo: Callable[[], str] | None = None


@dataclass
class SagaResult:
    ok: bool
    completed: list[str] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    failed: str | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = list(self.log)
        lines.append(f"結果: {'成功' if self.ok else '失敗'}"
                     f" / 実行済み {len(self.completed)} 件"
                     f" / 打ち消し {len(self.compensated)} 件")
        return "\n".join(lines)


class Saga:
    """打ち消し付きの手順。分散トランザクションの理論は扱わない（非スコープ）。

    ここで実装するのは「失敗したら、やったことを逆順に打ち消す」だけである。
    それでも、何もしないより桁違いにましな状態になる。
    """

    def run(self, actions: list[Action]) -> SagaResult:
        done: list[Action] = []
        log: list[str] = []
        for action in actions:
            try:
                out = action.do()
            except Exception as exc:  # noqa: BLE001
                log.append(f"× {action.name}: {exc}")
                compensated: list[str] = []
                for prev in reversed(done):
                    if prev.undo is None:
                        log.append(f"! {prev.name}: 打ち消せません（undo が無い）")
                        continue
                    log.append(f"↩ {prev.name}: {prev.undo()}")
                    compensated.append(prev.name)
                return SagaResult(False, [a.name for a in done], compensated,
                                  action.name, str(exc), log)
            log.append(f"○ {action.name}: {out}")
            done.append(action)
        return SagaResult(True, [a.name for a in done], [], None, None, log)


if __name__ == "__main__":
    import subprocess

    from faults import CHAT_MESSAGE, FaultInjector
    from idempotency import (active_expenses, count_rows, expense_key,
                             submit_expense_once)

    from agentkit.biztools import book_room, send_message

    def _reset() -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                       check=True, capture_output=True)

    _reset()
    key = expense_key("EMP-003", 12_000)
    broken_send = FaultInjector(send_message, fail_on=(1,), when="before",
                                message=CHAT_MESSAGE)
    result = Saga().run([
        Action("会議室を予約", lambda: book_room("うみかぜ", "10:00", 60),
               lambda: cancel_booking("うみかぜ", "10:00")),
        Action("経費を申請",
               lambda: submit_expense_once("高橋 涼", 12_000, "備品",
                                           idempotency_key=key),
               lambda: cancel_expense_by_key(key)),
        Action("参加者へ連絡",
               lambda: broken_send(to="EMP-003", body="報告会は10時からです。")),
    ])
    print(result.render())
    print(f"最終状態: bookings {count_rows('bookings')} 行 / "
          f"有効な申請 {active_expenses()} 件 / messages {count_rows('messages')} 行")
    _reset()
