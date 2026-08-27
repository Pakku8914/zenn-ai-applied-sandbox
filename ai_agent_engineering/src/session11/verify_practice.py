#!/usr/bin/env python3
"""セッション11の練習問題の自己検証。

本文・practice・solutions に載せた主張と数値をここで機械判定する。
1つでも満たさなければ非0で終了するので、出力を読んで判断する必要はない。

    docker compose exec app python src/session11/verify_practice.py

この章の演習は**実際に副作用を出す**（経費が増える・予約が入る）。冒頭と末尾で
`tools/make_data.py` を実行してデータを初期状態に戻す。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import (book_room, build_registry,  # noqa: E402
                               send_message, submit_expense)
from agentkit.clock import StepClock  # noqa: E402
from agentkit.llm import FlakyClient, ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402
from backoff import RecordingSleeper, backoff_delay  # noqa: E402
from compensate import (Action, Saga, cancel_booking,  # noqa: E402
                        cancel_expense_by_key)
from failure_kinds import (HANDOFF, PARTIAL, PERMANENT, RETRY_ALTERED,  # noqa: E402
                           RETRY_SAME, STOP, TRANSIENT, UNKNOWN,
                           classify_error, has_alternative, retry_decision)
from faults import CHAT_MESSAGE, FaultInjector  # noqa: E402
from guards import (RunLimits, brief_call, call_key, detect_alternating,  # noqa: E402
                    detect_loop, detect_repeat, uncertain_effects)
from idempotency import (active_expenses, book_room_if_free,  # noqa: E402
                         build_registry_with_flaky_submit,
                         build_submit_registry, count_rows, expense_key,
                         submit_after_precheck, submit_expense_once)
from retry_runner import (ReliableRunner, llm_calls, retry_blindly,  # noqa: E402
                          retry_guarded)
from retry_scenarios import (CASES, EXPENSE_SUBMIT, LONG_REPORT,  # noqa: E402
                             LOOP_ALTERNATING, TASK_BOOK, TASK_LONG,
                             TASK_SUBMIT)

failures: list[str] = []
TASK_REPORT = "2026年8月の経費レポートを作成してください"


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def reset() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


reset()

# --- 1. 失敗の切り分け ------------------------------------------------------
print("\n[1] 失敗の切り分けと再試行の判断")
CONFLICT = ("みなと の 10:00 は既に予約されています。別の時間帯（例: 11:00）"
            "または別の会議室を指定してください。")
NO_ROOM = "会議室 'かもめ' は存在しません。指定できる会議室: うみかぜ, ふ頭, みなと, 大会議室"
TOO_LONG = "連続利用は4時間（240分）までです。分割して予約してください。"
CONNECT = ("経費システムに接続できませんでした（一時的な障害）。"
           "しばらく待ってから同じ内容で再実行してください。")
NO_REPLY = ("経費システムから応答が返りませんでした（タイムアウト）。"
            "申請が登録されたかどうかは確認できません。")
INTERNAL = "内部エラー（ZeroDivisionError）"

check("競合は恒久的に分類される", classify_error(CONFLICT) == PERMANENT,
      classify_error(CONFLICT))
check("接続不可は一時的に分類される", classify_error(CONNECT) == TRANSIENT)
check("応答なしは部分的に分類される", classify_error(NO_REPLY) == PARTIAL)
check("内部エラーは分類できない", classify_error(INTERNAL) == UNKNOWN)
check("競合は代替案を示している", has_alternative(CONFLICT))
check("応答なしは代替案を示さない", not has_alternative(NO_REPLY))

check("競合は引数を変えて再試行",
      retry_decision(CONFLICT, idempotent=False).action == RETRY_ALTERED)
check("存在しない会議室も引数を変えて再試行",
      retry_decision(NO_ROOM, idempotent=False).action == RETRY_ALTERED)
check("連続利用の上限も引数を変えて再試行",
      retry_decision(TOO_LONG, idempotent=False).action == RETRY_ALTERED)
check("一時的×冪等は同じ引数で再試行",
      retry_decision(CONNECT, idempotent=True).action == RETRY_SAME)
check("一時的×冪等でないは人に渡す",
      retry_decision(CONNECT, idempotent=False).action == HANDOFF)
check("部分的×冪等は同じ引数で再試行",
      retry_decision(NO_REPLY, idempotent=True).action == RETRY_SAME)
check("部分的×冪等でないは人に渡す",
      retry_decision(NO_REPLY, idempotent=False).action == HANDOFF)
check("分類できない失敗は人に渡す",
      retry_decision(INTERNAL, idempotent=True).action == HANDOFF)
check("上限を超えたら人に渡す",
      retry_decision(CONNECT, idempotent=True, attempts=2, max_retries=1).action
      == HANDOFF)
check("代替案の無い恒久的失敗は再試行しない",
      retry_decision("権限がありません。", idempotent=True).action == STOP)

# --- 2. 指数バックオフ ------------------------------------------------------
print("\n[2] 指数バックオフ（実時間では待たない）")
delays = [backoff_delay(i) for i in range(6)]
check("待機は 0.5 から倍々で 8.0 で頭打ち",
      delays == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0], str(delays))
sleeper = RecordingSleeper()
for d in delays[:3]:
    sleeper.sleep(d)
check("待機の合計を記録している", sleeper.total == 3.5 and sleeper.count == 3,
      f"total={sleeper.total} count={sleeper.count}")

# --- 3. 障害の注入は2種類ある -----------------------------------------------
print("\n[3] 副作用の前に失敗するのか、あとに失敗するのか")
calls = {"n": 0}


def _counted(**_kwargs) -> str:
    calls["n"] += 1
    return "実行しました"


for when, expected in (("before", 0), ("after", 1)):
    calls["n"] = 0
    injected = FaultInjector(_counted, fail_on=(1,), when=when)
    raised = False
    try:
        injected()
    except ToolError:
        raised = True
    check(f"when={when} は例外を投げる", raised)
    check(f"when={when} の実行回数は {expected}", calls["n"] == expected,
          f"実際 {calls['n']}")

# --- 4. 3回に1回失敗する状況での完走率 --------------------------------------
print("\n[4] 一時的な失敗を再試行で吸収できるか")


def run_arm(fail_on: tuple[int, ...], retries: int | None) -> tuple[int, int, float]:
    done = 0
    total_calls = 0
    shared = RecordingSleeper()
    for _name, task, scenario, _turns in CASES:
        reset()
        flaky = FlakyClient(ScriptedClient(scenario), fail_on=fail_on)
        if retries is None:
            traj = ReActAgent(flaky, build_registry(), max_steps=8).run(task)
        else:
            traj = ReliableRunner(flaky, build_registry(), max_retries=retries,
                                  sleeper=shared).run(task)
        done += int(traj.stop_reason == "done")
        total_calls += flaky.count
    return done, total_calls, shared.total


EVERY_THIRD = tuple(range(3, 40, 3))
plain = run_arm(EVERY_THIRD, None)
check("再試行なしの完走は 1/4・LLM 11回・待機 0.0秒", plain == (1, 11, 0.0), str(plain))
retried = run_arm(EVERY_THIRD, 1)
check("上限1回の再試行で完走 4/4・LLM 19回・待機 2.0秒", retried == (4, 19, 2.0),
      str(retried))

print("\n[5] 同じ呼び出しが2回続けて失敗する場合")
short = run_arm((3, 4), 1)
check("上限1回では完走 1/4・LLM 14回・待機 1.5秒", short == (1, 14, 1.5), str(short))
deep = run_arm((3, 4), 3)
check("上限3回なら完走 4/4・LLM 21回・待機 4.5秒", deep == (4, 21, 4.5), str(deep))

# --- 6. 冪等性と二重申請 ----------------------------------------------------
print("\n[6] 冪等でない操作を再試行したときの副作用")
SUBMIT_ARGS = {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "note": "取引先との打ち合わせ",
               "idempotency_key": expense_key("EMP-003", 68_000)}
SUBMIT_CALL = ToolCall("verify-submit", "submit_expense", SUBMIT_ARGS)


def side_effect_rows(idempotent: bool, how) -> tuple[int, bool]:
    reset()
    before = count_rows("expenses")
    registry = build_submit_registry(idempotent=idempotent)
    result = how(registry)
    return count_rows("expenses") - before, result.ok


rows, ok = side_effect_rows(False, lambda reg: reg.call(SUBMIT_CALL))
check("再試行しないと 1 件登録されたまま失敗になる", (rows, ok) == (1, False),
      f"{rows} 件 ok={ok}")
rows, ok = side_effect_rows(
    False, lambda reg: retry_blindly(reg, SUBMIT_CALL, max_retries=1)[0])
check("無条件に再試行すると 2 件（二重申請）", (rows, ok) == (2, True),
      f"{rows} 件 ok={ok}")
rows, ok = side_effect_rows(
    False, lambda reg: retry_guarded(reg, SUBMIT_CALL, max_retries=1)[0])
check("判断つきなら冪等でないので再試行しない（1 件・失敗）",
      (rows, ok) == (1, False), f"{rows} 件 ok={ok}")
rows, ok = side_effect_rows(
    True, lambda reg: retry_guarded(reg, SUBMIT_CALL, max_retries=1)[0])
check("冪等キー付きなら再試行しても 1 件で成功", (rows, ok) == (1, True),
      f"{rows} 件 ok={ok}")

# --- 7. 冪等化の3手法 -------------------------------------------------------
print("\n[7] 冪等化の3手法")
key = expense_key("EMP-003", 68_000)

reset()
before = count_rows("expenses")
submit_expense_once("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
msg = submit_expense_once("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
check("A 冪等キー：2回呼んで 1 件", count_rows("expenses") - before == 1)
check("A 2回目は受け付け済みと分かる", "既に受け付けています" in msg, msg[:40])

reset()
before = count_rows("bookings")
book_room_if_free("うみかぜ", "10:00")
book_room_if_free("うみかぜ", "10:00")
check("B 条件付き更新：2回呼んで 1 件", count_rows("bookings") - before == 1)

reset()
before = count_rows("bookings")
book_room("うみかぜ", "10:00")
book_room("うみかぜ", "10:00")
check("B 素の book_room は 2 件になる", count_rows("bookings") - before == 2)

reset()
before = count_rows("expenses")
submit_after_precheck("高橋 涼", 68_000, "接待交際費", idempotency_key=key,
                      interleave=lambda: submit_expense(
                          "高橋 涼", 68_000, "接待交際費", idempotency_key=key))
check("C 事前確認：割り込みが入ると 2 件", count_rows("expenses") - before == 2)

reset()
before = count_rows("expenses")
submit_after_precheck("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
submit_after_precheck("高橋 涼", 68_000, "接待交際費", idempotency_key=key)
check("C 割り込みが無ければ 1 件", count_rows("expenses") - before == 1)

# --- 8. 循環検出 ------------------------------------------------------------
print("\n[8] 循環の検出")
same = ["book_room:A", "book_room:A", "book_room:A"]
alt = ["book_room:A", "book_room:B", "book_room:A", "book_room:B"]
normal = ["get_policy:X", "list_expenses:Y", "write_file:Z"]
check("同じ引数の3連続を検出する", detect_repeat(same) and detect_loop(same))
check("交互の繰り返しを検出する",
      detect_alternating(alt) and not detect_repeat(alt) and detect_loop(alt))
check("正常な3手は循環と見なさない", not detect_loop(normal))
check("window=0 で循環検出を切れる", not detect_loop(same, window=0))
check("引数まで含めて同じ行動と見なす",
      call_key(ToolCall("a", "book_room", {"room": "みなと"}))
      != call_key(ToolCall("b", "book_room", {"room": "うみかぜ"})))


def run_guarded(scenario, task: str, **kwargs):
    reset()
    return ReliableRunner(ScriptedClient(scenario), build_registry(), **kwargs).run(task)


def shape(traj) -> tuple[str, int, int, int]:
    return (traj.stop_reason, len(traj.steps), len(traj.tool_names), llm_calls(traj))


loop_off = run_guarded("max_steps_loop", "経費の規程を調べてください",
                       limits=RunLimits(max_steps=6), loop_window=0)
check("循環検出なしなら上限まで6手回る", shape(loop_off) == ("max_steps", 6, 6, 6),
      str(shape(loop_off)))
loop_on = run_guarded("max_steps_loop", "経費の規程を調べてください",
                      limits=RunLimits(max_steps=6), loop_window=3)
check("循環検出ありなら3手で打ち切る", shape(loop_on) == ("loop_detected", 3, 3, 3),
      str(shape(loop_on)))
loop_alt = run_guarded(LOOP_ALTERNATING, TASK_BOOK, limits=RunLimits(max_steps=6))
check("交互の循環は4手で打ち切る", shape(loop_alt) == ("loop_detected", 4, 4, 4),
      str(shape(loop_alt)))
check("打ち切りの理由が最終回答に入る",
      "同じ行動の繰り返し" in (loop_alt.final or ""), (loop_alt.final or "")[:40])

# --- 9. 上限 ----------------------------------------------------------------
print("\n[9] コスト上限と時間上限")
by_tools = run_guarded("expense_report", TASK_REPORT,
                       limits=RunLimits(max_tool_calls=2))
check("ツール呼び出し上限2で2手で止まる", shape(by_tools) == ("budget", 2, 2, 2),
      str(shape(by_tools)))
by_time = run_guarded("expense_report", TASK_REPORT,
                      limits=RunLimits(deadline_seconds=90),
                      clock=StepClock(step_seconds=30))
check("時間上限90秒で2手で止まる", shape(by_time) == ("budget", 2, 2, 2),
      str(shape(by_time)))
check("上限は達したら止める（超えない）", len(by_tools.tool_names) == 2,
      str(by_tools.tool_names))

finals = {}
for mode in ("fail", "partial", "handoff"):
    traj = run_guarded(LONG_REPORT, TASK_LONG, limits=RunLimits(max_tool_calls=4),
                       on_limit=mode)
    finals[mode] = traj.final or ""
    check(f"on_limit={mode} は budget で4手で止まる",
          shape(traj) == ("budget", 4, 4, 4), str(shape(traj)))
check("fail は完了していないと言う", "完了していません" in finals["fail"])
check("partial は途中結果を返す",
      "済んだ操作" in finals["partial"] and "write_file" in finals["partial"])
check("handoff は5項目の引き継ぎ書を返す",
      all(k in finals["handoff"] for k in
          ("頼まれたこと", "止まった理由", "済んでいて取り消していない操作",
           "実行されたか分からない操作", "次にやること")))

# --- 10. 実行されたか分からないまま「できました」と言わせない ---------------
print("\n[10] 失敗の伝え方")
reset()
registry = build_registry_with_flaky_submit(idempotent=False, fail_on=(1,),
                                            when="after")
before = count_rows("expenses")
traj = ReliableRunner(ScriptedClient(EXPENSE_SUBMIT), registry, max_retries=1).run(
    TASK_SUBMIT)
check("モデルが完了と言っても done にしない", traj.stop_reason == "error",
      traj.stop_reason)
check("副作用は1件出ている", count_rows("expenses") - before == 1)
check("実行の有無が不明な操作として記録される",
      len(uncertain_effects(traj)) == 1, str(uncertain_effects(traj)))
check("引き継ぎ書に冪等キーが載る",
      expense_key("EMP-003", 68_000) in (traj.final or ""))
check("次にやることが照合であると書いてある",
      "照合" in (traj.final or ""))
check("短い表記に切り詰められている",
      brief_call(ToolCall("x", "write_file", {"content": "あ" * 40})).endswith("…)"))

# --- 11. 補償 ---------------------------------------------------------------
print("\n[11] 補償（逆順に打ち消す）")
reset()
comp_key = expense_key("EMP-003", 12_000)
broken_send = FaultInjector(send_message, fail_on=(1,), when="before",
                            message=CHAT_MESSAGE)
result = Saga().run([
    Action("会議室を予約", lambda: book_room("うみかぜ", "10:00", 60),
           lambda: cancel_booking("うみかぜ", "10:00")),
    Action("経費を申請",
           lambda: submit_expense_once("高橋 涼", 12_000, "備品",
                                       idempotency_key=comp_key),
           lambda: cancel_expense_by_key(comp_key)),
    Action("参加者へ連絡",
           lambda: broken_send(to="EMP-003", body="報告会は10時からです。")),
])
check("3つ目で失敗する", not result.ok and result.failed == "参加者へ連絡")
check("実行済み2件を逆順に打ち消す",
      result.compensated == ["経費を申請", "会議室を予約"], str(result.compensated))
check("予約は解放される（行を消す）", count_rows("bookings") == 0)
check("メッセージは送られていない", count_rows("messages") == 0)
check("有効な申請は元の6件に戻る", active_expenses() == 6, str(active_expenses()))
check("申請の行そのものは残る（取り消しの記録）", count_rows("expenses") == 7,
      str(count_rows("expenses")))
check("補償は冪等（もう一度打ち消しても増減しない）",
      "打ち消す申請はありません" in cancel_expense_by_key(comp_key))
try:
    cancel_expense_by_key("")
    check("キーが空なら打ち消しを拒否する", False, "例外が出なかった")
except ToolError:
    check("キーが空なら打ち消しを拒否する", True)

reset()
if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション11の練習問題の検証はすべて成功しました。")
