#!/usr/bin/env python3
"""再試行・冪等性・打ち切り・補償の実測（セッション11の数値の出典）。

決定的なので何度実行しても同じ数値になる。
  - LLM の失敗は乱数ではなく「N 回目の呼び出し」で注入する
  - 待機は記録するだけで実時間では待たない（`RecordingSleeper`）
  - 副作用の回数は軌跡ではなく **data/ の行数** で数える

    docker compose exec app python tools/bench_retry.py

ブロックごとに `tools/make_data.py` でデータを初期状態に戻すので、
実行後に業務データが汚れたままになることはない。
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S11 = ROOT / "src" / "session11"
for _p in (str(ROOT), str(S11)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_data  # noqa: E402  （tools/ 直下）
from agentkit.biztools import book_room, build_registry, send_message  # noqa: E402
from agentkit.clock import StepClock  # noqa: E402
from agentkit.llm import FlakyClient, ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from backoff import RecordingSleeper  # noqa: E402
from compensate import Action, Saga, cancel_booking, cancel_expense_by_key  # noqa: E402
from faults import CHAT_MESSAGE, FaultInjector  # noqa: E402
from guards import RunLimits  # noqa: E402
from idempotency import (active_expenses, build_registry_with_flaky_submit,  # noqa: E402
                         build_submit_registry, count_rows, expense_key,
                         submit_expense_once)
from retry_runner import (ReliableRunner, llm_calls, retry_blindly,  # noqa: E402
                          retry_guarded)
from retry_scenarios import (CASES, LOOP_ALTERNATING, TASK_BOOK,  # noqa: E402
                             TASK_LONG, TASK_SUBMIT, EXPENSE_SUBMIT, LONG_REPORT)

SUBMIT_ARGS = {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "note": "取引先との打ち合わせ",
               "idempotency_key": expense_key("EMP-003", 68_000)}
SUBMIT_CALL = ToolCall("bench-submit", "submit_expense", SUBMIT_ARGS)


def reset() -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        make_data.main()


def line(*cells: str) -> str:
    return " | ".join(cells)


# ---------------------------------------------------------------------------
def block_single_failure() -> None:
    print("=== ① 3回に1回失敗する（通しの呼び出し番号が3の倍数で失敗）===")
    print(line("条件", "完走", "打ち切り", "LLM呼び出し", "待機の合計"))
    for label, retries in (("再試行なし（素の ReActAgent）", None),
                           ("再試行あり（上限1回）", 1)):
        done = 0
        calls = 0
        sleeper = RecordingSleeper()
        for _name, task, scenario, _turns in CASES:
            reset()
            flaky = FlakyClient(ScriptedClient(scenario), fail_on=tuple(range(3, 40, 3)))
            if retries is None:
                traj = ReActAgent(flaky, build_registry(), max_steps=8).run(task)
            else:
                traj = ReliableRunner(flaky, build_registry(), max_retries=retries,
                                      sleeper=sleeper).run(task)
            done += int(traj.stop_reason == "done")
            calls += flaky.count
        print(line(label, str(done), str(len(CASES) - done), str(calls),
                   f"{sleeper.total} 秒"))


def block_double_failure() -> None:
    print("\n=== ② 同じ呼び出しが2回続けて失敗する（3回目と4回目で失敗）===")
    print(line("条件", "完走", "打ち切り", "LLM呼び出し", "待機の合計"))
    for label, retries in (("再試行あり（上限1回）", 1), ("再試行あり（上限3回）", 3)):
        done = 0
        calls = 0
        sleeper = RecordingSleeper()
        for _name, task, scenario, _turns in CASES:
            reset()
            flaky = FlakyClient(ScriptedClient(scenario), fail_on=(3, 4))
            traj = ReliableRunner(flaky, build_registry(), max_retries=retries,
                                  sleeper=sleeper).run(task)
            done += int(traj.stop_reason == "done")
            calls += flaky.count
        print(line(label, str(done), str(len(CASES) - done), str(calls),
                   f"{sleeper.total} 秒"))


def block_side_effects() -> None:
    print("\n=== ③ 冪等でない操作を再試行したときの副作用（expenses の行数で数える）===")
    print(line("やり方", "追加行数", "成功", "備考"))

    def measure(label: str, idempotent: bool, how, note: str) -> None:
        reset()
        before = count_rows("expenses")
        registry = build_submit_registry(idempotent=idempotent)
        result, _attempts, _waited = how(registry)
        print(line(label, str(count_rows("expenses") - before),
                   "はい" if result.ok else "いいえ", note))

    measure("再試行しない", False,
            lambda reg: (reg.call(SUBMIT_CALL), 1, 0.0),
            "申請は登録済みなのに失敗として報告される")
    measure("無条件に1回再試行（アンチパターン）", False,
            lambda reg: retry_blindly(reg, SUBMIT_CALL, max_retries=1),
            "二重申請になる")
    measure("判断つきの再試行（冪等でない）", False,
            lambda reg: retry_guarded(reg, SUBMIT_CALL, max_retries=1),
            "再試行せず人に渡す")
    measure("冪等キー付きのツールを1回再試行", True,
            lambda reg: retry_guarded(reg, SUBMIT_CALL, max_retries=1),
            "重複を吸収して1件のまま")
    reset()


def block_loops_and_limits() -> None:
    print("\n=== ④ 循環と上限 ===")
    print(line("条件", "停止理由", "ステップ", "ツール呼び出し", "手数"))
    reset()
    rows: list[tuple[str, object]] = []

    rows.append(("上限だけ（max_steps=6）",
                 ReliableRunner(ScriptedClient("max_steps_loop"), build_registry(),
                                limits=RunLimits(max_steps=6),
                                loop_window=0).run("経費の規程を調べてください")))
    rows.append(("同じ引数の連続を検出（window=3）",
                 ReliableRunner(ScriptedClient("max_steps_loop"), build_registry(),
                                limits=RunLimits(max_steps=6),
                                loop_window=3).run("経費の規程を調べてください")))
    rows.append(("交互の繰り返しを検出（ABAB）",
                 ReliableRunner(ScriptedClient(LOOP_ALTERNATING), build_registry(),
                                limits=RunLimits(max_steps=6)).run(TASK_BOOK)))
    rows.append(("ツール呼び出し上限 2",
                 ReliableRunner(ScriptedClient("expense_report"), build_registry(),
                                limits=RunLimits(max_tool_calls=2)).run(
                     "2026年8月の経費レポートを作成してください")))
    rows.append(("時間上限 90秒（1手30秒の時計）",
                 ReliableRunner(ScriptedClient("expense_report"), build_registry(),
                                limits=RunLimits(deadline_seconds=90),
                                clock=StepClock(step_seconds=30)).run(
                     "2026年8月の経費レポートを作成してください")))
    for label, traj in rows:
        print(line(label, traj.stop_reason, str(len(traj.steps)),
                   str(len(traj.tool_names)), str(llm_calls(traj))))
    reset()


def block_on_limit() -> None:
    print("\n=== ⑤ 上限に達したときに何を返すか（on_limit）===")
    for mode in ("fail", "partial", "handoff"):
        reset()
        traj = ReliableRunner(ScriptedClient(LONG_REPORT),
                              build_registry(),
                              limits=RunLimits(max_tool_calls=4),
                              on_limit=mode).run(TASK_LONG)
        print(f"--- on_limit={mode} / stop_reason={traj.stop_reason} / "
              f"ステップ={len(traj.steps)} ---")
        print(traj.final)
    reset()


def block_handoff() -> None:
    print("\n=== ⑥ 実行されたか分からないまま終わったときの引き継ぎ書 ===")
    reset()
    registry = build_registry_with_flaky_submit(idempotent=False, fail_on=(1,),
                                                when="after")
    before = count_rows("expenses")
    traj = ReliableRunner(ScriptedClient(EXPENSE_SUBMIT), registry,
                          max_retries=1).run(TASK_SUBMIT)
    print(f"stop_reason={traj.stop_reason} / ステップ={len(traj.steps)} / "
          f"expenses の増分={count_rows('expenses') - before} 行")
    print(traj.final)
    reset()


def block_compensation() -> None:
    print("\n=== ⑦ 途中で失敗した処理の補償 ===")
    reset()
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
    reset()


def main() -> None:
    block_single_failure()
    block_double_failure()
    block_side_effects()
    block_loops_and_limits()
    block_on_limit()
    block_handoff()
    block_compensation()
    print("\n（データは初期状態に戻してあります）")


if __name__ == "__main__":
    main()
