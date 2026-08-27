#!/usr/bin/env python3
"""セッション6の自己検証：状態機械・チェックポイント・再開が主張どおりに動くこと。

本文（body / practice / solutions）に載せた出力・数値もここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文を直すこと。
検証の前後で `tools/make_data.py` を走らせるので、データは初期状態に戻る。

    python src/session06/verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import WORKSPACE, build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.state import Checkpoint  # noqa: E402
from durability import (bookings_rows, crash_matrix, fresh_dir,  # noqa: E402
                        granularity_report, load_checkpoint_single,
                        partial_write_demo, reset_data, save_checkpoint_atomic,
                        single_file_crash_demo)
from ex_path import (all_edges, traj_to_mermaid,  # noqa: E402
                     uncovered_transitions)
from modes import (guess_state_from_history, history_only,  # noqa: E402
                   machine_guard, prompt_state_antipattern, state_view_shape,
                   struct_only)
from runner import (ResumableRunner, SimulatedCrash, llm_calls,  # noqa: E402
                    render_run)
from scenarios import CLEAN, OUT_OF_ORDER, RESEARCH, RESEARCH_AUTO, STUCK  # noqa: E402
from states import TaskState, build_machine, find_violations  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
TASK_ID = "TASK-006"
DIR = ROOT / "traces" / "checkpoints" / "session06_verify"

FULL_TOOLS = ["get_policy", "list_expenses", "search_docs", "write_file",
              "book_room", "book_room"]
FULL_EVENTS = ["plan_ready", "need_more", "collected", "violation_found",
               "draft_saved", "conflict", "slot_chosen", "booked", ""]

EXPECTED_RUN = """task_id=TASK-006 stop_reason=done 手数=9
  step 0 <planning> （ツールなし） -> plan_ready
  step 1 <collecting> get_policy:ok [serial] -> need_more
  step 2 <collecting> list_expenses:ok search_docs:ok [parallel] -> collected
  step 3 <checking> （ツールなし） -> violation_found
  step 4 <drafting> write_file:ok [serial] -> draft_saved
  step 5 <booking> book_room:NG [serial] -> conflict
  step 6 <rescheduling> （ツールなし） -> slot_chosen
  step 7 <booking> book_room:ok [serial] -> booked
  step 8 <done> （ツールなし） -> （遷移なし）
  final: 規程違反の疑いがある申請 2 件（EXP-0002 / EXP-0004）をレポートに整理し、\
報告会の会議室（みなと 11:00）を予約しました。"""

EXPECTED_PATH = """stateDiagram-v2
    planning --> collecting: plan_ready
    collecting --> collecting: need_more
    collecting --> checking: collected
    checking --> drafting: violation_found
    drafting --> booking: draft_saved
    booking --> rescheduling: conflict
    rescheduling --> booking: slot_chosen
    booking --> done: booked"""

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def build(scenario, **kwargs) -> ResumableRunner:
    kwargs.setdefault("task_id", TASK_ID)
    kwargs.setdefault("checkpoint_dir", DIR)
    return ResumableRunner(ScriptedClient(scenario), build_registry(), **kwargs)


def events(traj) -> list[str]:
    return [s.usage.get("event", "") for s in traj.steps]


# --- 1. 完走：状態機械のとおりに進むか -------------------------------------
reset_data()
fresh_dir(DIR)
runner = build(RESEARCH)
traj = runner.run(TASK)

check("完走の軌跡が本文の表示と一致する", render_run(traj) == EXPECTED_RUN,
      "" if render_run(traj) == EXPECTED_RUN else "\n" + render_run(traj))
check("停止理由と最終状態が done になる",
      traj.stop_reason == "done" and runner.state.state == "done",
      f"{traj.stop_reason} / {runner.state.state}")
check("呼ばれたツールの並びが設計どおり", traj.tool_names == FULL_TOOLS,
      str(traj.tool_names))
check("遷移の並びが設計どおり", events(traj) == FULL_EVENTS, str(events(traj)))
check("規程違反の疑いを2件検出する",
      runner.state.violations == ["EXP-0002", "EXP-0004"],
      str(runner.state.violations))
check("会議室の予約は1件だけ", bookings_rows() == 1, f"{bookings_rows()} 行")
check("予約できた枠は 11:00（10:00 は競合する）",
      runner.state.booking == {"room": "みなと", "start": "11:00"},
      str(runner.state.booking))

report = WORKSPACE / "session06" / "report.md"
body = report.read_text(encoding="utf-8") if report.exists() else ""
check("レポートは状態から組み立てられている",
      "EXP-0002" in body and "EXP-0004" in body and "規程違反の疑い: 2 件" in body,
      f"{len(body)} 文字")

check("状態に search_docs の本文は保存しない（判断に使わないため）",
      sorted(runner.state.materials) == ["get_policy", "list_expenses"],
      str(sorted(runner.state.materials)))
check("手数（モデルに聞いた回数）は9回",
      runner.state.llm_calls == 9 and llm_calls(traj) == 9,
      f"{runner.state.llm_calls} / {llm_calls(traj)}")

# --- 2. 決定性：同じ入力なら同じ軌跡 ---------------------------------------
first = render_run(traj)
reset_data()
fresh_dir(DIR)
second = render_run(build(RESEARCH).run(TASK))
check("2回走らせて軌跡が一致する", first == second)

# --- 3. 状態と軌跡が JSON を往復しても壊れない -----------------------------
saved = Checkpoint.load(TASK_ID, DIR)
check("保存した軌跡から状態と遷移を読み戻せる",
      len(saved.trajectory.steps) == 9
      and saved.trajectory.steps[2].usage["event"] == "collected"
      and saved.trajectory.steps[2].usage["state"] == "collecting"
      and saved.state["state"] == "done",
      f"{len(saved.trajectory.steps)} steps / {saved.state['state']}")
restored = TaskState.from_dict(saved.state)
check("状態は JSON を往復しても同じ", restored.to_dict() == saved.state)

# --- 4. 状態機械そのもの ---------------------------------------------------
mermaid = build_machine().to_mermaid()
lines = mermaid.splitlines()
check("状態遷移図をコードから出力できる",
      lines[0] == "stateDiagram-v2" and len(lines) == 19
      and "    collecting --> collecting: need_more" in lines
      and "    checking --> wrapping_up: no_violation" in lines
      and "    booking --> rescheduling: conflict" in lines,
      f"{len(lines)} 行")

guard = machine_guard()
check("許されていない遷移は例外になる",
      guard["止まったか"] and "状態 'collecting' でイベント 'booked'" in guard["メッセージ"]
      and "['collected', 'fatal', 'need_more']" in guard["メッセージ"],
      guard["メッセージ"])

# --- 5. 段階を飛ばした操作は実行前に止まる ---------------------------------
reset_data()
fresh_dir(DIR)
ooo = build(OUT_OF_ORDER, max_steps=4)
ooo_traj = ooo.run(TASK)
first_error = ooo_traj.steps[1].results[0].error or ""
check("collecting の段階では book_room を実行できない",
      not ooo_traj.steps[1].results[0].ok
      and "いまは 'collecting' の段階" in first_error
      and "get_policy, list_expenses, search_docs" in first_error,
      first_error)
check("拒否されたので予約は1件も入っていない", bookings_rows() == 0,
      f"{bookings_rows()} 行")
check("打ち切りは行動の前に判定される",
      ooo_traj.stop_reason == "max_steps" and len(ooo_traj.steps) == 4
      and ooo.state.state == "checking",
      f"{ooo_traj.stop_reason} / {len(ooo_traj.steps)} / {ooo.state.state}")

# --- 6. ループには上限を置く -----------------------------------------------
reset_data()
fresh_dir(DIR)
stuck = build(STUCK)
stuck_traj = stuck.run(TASK)
check("同じ状態に留まり続けたら loop_detected で止まる",
      stuck_traj.stop_reason == "loop_detected" and stuck.state.state == "failed"
      and len(stuck_traj.steps) == 4
      and stuck_traj.tool_names == ["get_policy"] * 3,
      f"{stuck_traj.stop_reason} / {len(stuck_traj.steps)} / {stuck_traj.tool_names}")

# --- 7. 分岐：違反が0件なら別の枝へ ---------------------------------------
reset_data()
fresh_dir(DIR)
clean = build(CLEAN, task_id="TASK-006C", threshold=200_000)
clean_traj = clean.run(TASK)
check("違反0件なら wrapping_up を通って done に着く",
      events(clean_traj) == ["plan_ready", "need_more", "collected",
                             "no_violation", "reported", ""]
      and clean.state.state == "done" and len(clean_traj.steps) == 6,
      str(events(clean_traj)))
check("違反0件の道では会議室を予約しない", bookings_rows() == 0,
      f"{bookings_rows()} 行")
check("判定基準は状態に含まれる（再開後もぶれない）",
      clean.state.threshold == 200_000 and clean.state.violations == [],
      str(clean.state.threshold))
check("判定基準を変えると違反の件数が変わる",
      find_violations(clean.state.materials["list_expenses"], 50_000)
      == ["EXP-0002", "EXP-0004"]
      and find_violations(clean.state.materials["list_expenses"], 200_000) == [])

# --- 8. 打ち切りからの再開（上限を上げて続ける） ---------------------------
reset_data()
fresh_dir(DIR)
short = build(RESEARCH, max_steps=2)
short_traj = short.run(TASK)
check("上限2手で打ち切られる",
      short_traj.stop_reason == "max_steps" and len(short_traj.steps) == 2
      and short.state.state == "collecting",
      f"{short_traj.stop_reason} / {len(short_traj.steps)} / {short.state.state}")
resumed = build(RESEARCH, max_steps=12)
resumed_traj = resumed.run(TASK, resume=True)
check("上限を上げて再開すると完走する（軌跡は打ち切らなかった場合と一致）",
      render_run(resumed_traj) == EXPECTED_RUN,
      "" if render_run(resumed_traj) == EXPECTED_RUN else "\n" + render_run(resumed_traj))

# --- 9. 強制終了からの再開（同じ結果に到達する） ---------------------------
reset_data()
fresh_dir(DIR)
crashed = build(RESEARCH)
try:
    crashed.run(TASK, crash_at=3)
    crash_raised = False
except SimulatedCrash:
    crash_raised = True
checkpoint = Checkpoint.load(TASK_ID, DIR)
check("step 3 の直前で落ちると、3手ぶんだけ保存されている",
      crash_raised and len(checkpoint.trajectory.steps) == 3
      and checkpoint.state["state"] == "checking",
      f"{len(checkpoint.trajectory.steps)} steps / {checkpoint.state['state']}")
restart = build(RESEARCH)
restart_traj = restart.run(TASK, resume=True)
check("チェックポイントから再開して同じ結果に到達する",
      render_run(restart_traj) == EXPECTED_RUN
      and restart_traj.tool_names == FULL_TOOLS,
      "" if render_run(restart_traj) == EXPECTED_RUN else "\n" + render_run(restart_traj))
check("再開しても副作用は1回だけ", bookings_rows() == 1, f"{bookings_rows()} 行")

for point in (1, 6):
    reset_data()
    fresh_dir(DIR)
    try:
        build(RESEARCH).run(TASK, crash_at=point)
    except SimulatedCrash:
        pass
    saved_steps = len(Checkpoint.load(TASK_ID, DIR).trajectory.steps)
    again_traj = build(RESEARCH).run(TASK, resume=True)
    check(f"crash_at={point} から再開しても同じ結果に到達する",
          saved_steps == point and render_run(again_traj) == EXPECTED_RUN
          and bookings_rows() == 1,
          f"保存 {saved_steps} 手 / 予約 {bookings_rows()} 行")

# --- 10. 再開位置を合わせ忘れるとどうなるか -------------------------------
reset_data()
fresh_dir(DIR)
try:
    build(RESEARCH).run(TASK, crash_at=3)
except SimulatedCrash:
    pass
forgot = build(RESEARCH)
forgot._sync_oracle = lambda position: None  # 位置を合わせない（よくある事故）
forgot_traj = forgot.run(TASK, resume=True)
check("オラクルの位置を合わせないと最初の一手からやり直しになる",
      forgot_traj.tool_names != FULL_TOOLS
      and forgot_traj.tool_names[-1] == "get_policy"
      and forgot.state.state == "failed" and forgot_traj.stop_reason == "error"
      and bookings_rows() == 0,
      f"{forgot_traj.tool_names} / {forgot_traj.stop_reason} / {forgot.state.state}")

# --- 11. 落ち方と再開の仕方で副作用の回数が変わる -------------------------
matrix = crash_matrix()
check("二重実行のマトリクスが本文の表と一致する",
      [row["bookings の行数"] for row in matrix] == [2, 1, 2, 1],
      str([(row["やり方"], row["bookings の行数"]) for row in matrix]))
check("どの行も手数9で done に着く（軌跡だけでは二重実行に気づけない）",
      all(row["手数"] == 9 and row["停止理由"] == "done" for row in matrix),
      str([(row["手数"], row["停止理由"]) for row in matrix]))

# 失敗した副作用のやり直しは安全（外部が変わっていないため）
for guard_mode in ("none", "ahead"):
    reset_data()
    fresh_dir(DIR)
    try:
        build(RESEARCH, guard=guard_mode).run(TASK, crash_before_save=5)
    except SimulatedCrash:
        pass
    rows_after_crash = bookings_rows()
    retried = build(RESEARCH, guard=guard_mode)
    retried_traj = retried.run(TASK, resume=True)
    check(f"失敗した予約の直後に落ちても二重予約にならない（guard={guard_mode}）",
          rows_after_crash == 0 and bookings_rows() == 1
          and len(retried_traj.steps) == 9 and retried_traj.stop_reason == "done",
          f"落ちた直後 {rows_after_crash} 行 → 再開後 {bookings_rows()} 行")

# --- 12. チェックポイントの粒度 -------------------------------------------
gran = granularity_report()
check("ステップ単位は9回保存し、やり直しは0手",
      gran[0] == {"粒度": "step", "完走時の保存回数": 9, "保存済みの手数": 6,
                  "やり直す手数": 0, "再開する状態": "rescheduling"},
      str(gran[0]))
check("サブゴール単位は5回保存し、やり直しは1手",
      gran[1] == {"粒度": "subgoal", "完走時の保存回数": 5, "保存済みの手数": 5,
                  "やり直す手数": 1, "再開する状態": "booking"},
      str(gran[1]))

gran4 = granularity_report(crash_at=4)
check("step 4 で落ちたとき、やり直す手数は 0 / 1 手",
      [(r["粒度"], r["やり直す手数"], r["再開する状態"]) for r in gran4]
      == [("step", 0, "drafting"), ("subgoal", 1, "checking")], str(gran4))
gran8 = granularity_report(crash_at=8)
check("step 8 で落ちたときは、どちらの粒度でもやり直しは 0 手",
      [(r["粒度"], r["やり直す手数"], r["再開する状態"]) for r in gran8]
      == [("step", 0, "done"), ("subgoal", 0, "done")], str(gran8))

# --- 13. 部分書き込みと原子的な保存 ---------------------------------------
partial = partial_write_demo()
check("本体に直接書いている途中で落ちると状態が読めなくなる",
      partial["直接書き込みで落ちた場合"] == "JSONDecodeError", str(partial))
check("tmp→rename なら落ちても直前の状態が生き残る",
      partial["tmp→rename で落ちた場合"] == "collecting", str(partial))

single = single_file_crash_demo()
check("1ファイル＋rename 1回なら軌跡と状態がずれない",
      single == {"読めた状態": "collecting", "軌跡の手数": 1,
                 "壊れた tmp が残っているか": True}, str(single))

atomic_dir = ROOT / "traces" / "checkpoints" / "session06_atomic"
fresh_dir(atomic_dir)
save_checkpoint_atomic(Checkpoint(TASK_ID, traj, runner.state.to_dict()), atomic_dir)
reloaded = Checkpoint.load(TASK_ID, atomic_dir)
check("軌跡も tmp→rename で保存できる（往復して同じ）",
      len(reloaded.trajectory.steps) == 9 and reloaded.state["state"] == "done",
      f"{len(reloaded.trajectory.steps)} steps")
single_dir = ROOT / "traces" / "checkpoints" / "session06_single"
check("1ファイル版も往復して同じ",
      load_checkpoint_single("TASK-006S", single_dir).state["state"] == "collecting")

# --- 14. 状態の持ち方3方式 -----------------------------------------------
hist = history_only()
check("履歴の文字列一致では「どこまで進んだか」を誤る",
      hist["推測した状態"] == "drafting" and hist["実際の状態"] == "collecting"
      and hist["履歴のメッセージ数"] == 3,
      str(hist))
check("推測が誤るのは、実行済みと実行予定が同じ文字列だから",
      guess_state_from_history([{"role": "assistant", "content": "次は write_file で保存する"}])
      == "drafting"
      and guess_state_from_history(
          [{"role": "assistant", "content": "最後に book_room で押さえる予定"}]) == "booking")
struct = struct_only()
check("構造体だけでは順序違反を止められない",
      struct["書き換え後の状態"] == "done" and struct["例外は出たか"] is False
      and struct["データと整合しているか"] is False, str(struct))

# --- 15. アンチパターン：状態をプロンプトの文字列で持つ -------------------
anti = prompt_state_antipattern()
lengths = anti["プロンプトの長さの推移"]
check("プロンプトに進捗を積み上げると長さが単調に増える",
      all(b > a for a, b in zip(lengths, lengths[1:]))
      and lengths == [17, 27, 37, 51],
      str(lengths))
check("言い換えられた進捗は読み戻せない（機械には読めない状態）",
      anti["読み戻せた進捗"] == ["G1", "G2"] and len(anti["書き込んだ進捗"]) == 3,
      str(anti["読み戻せた進捗"]))
view = state_view_shape()
check("状態の投影は鍵の集合が変わらない（機械が読める）", view["鍵は同じか"],
      str(view["鍵"]))

# --- 16. 決定的に決まる判断はモデルに聞かない -----------------------------
reset_data()
fresh_dir(DIR)
auto = build(RESEARCH_AUTO, auto_states=("checking", "rescheduling"))
auto_traj = auto.run(TASK)
check("checking と rescheduling を自動化すると手数が9→7に減る",
      len(auto_traj.steps) == 9 and llm_calls(auto_traj) == 7
      and auto.state.llm_calls == 7,
      f"steps={len(auto_traj.steps)} / 手数={llm_calls(auto_traj)}")
check("自動化しても結果は同じ（ツールの並びと遷移が一致）",
      auto_traj.tool_names == FULL_TOOLS and events(auto_traj) == FULL_EVENTS
      and auto_traj.stop_reason == "done", str(auto_traj.tool_names))
auto_in = auto_traj.total_tokens["input"]
full_in = traj.total_tokens["input"]
check("近似入力トークン（比較用）も減る", auto_in < full_in,
      f"自動化 {auto_in} < 全手動 {full_in}")

# --- 17. 軌跡から「実際に通った経路」を描く -------------------------------
check("通った経路の図が8本の遷移になる",
      traj_to_mermaid(traj) == EXPECTED_PATH, "\n" + traj_to_mermaid(traj))
check("定義18本のうち10本は今回の軌跡では通っていない",
      len(all_edges()) == 18 and len(uncovered_transitions(traj)) == 10
      and "wrapping_up --> done: reported" in uncovered_transitions(traj),
      f"定義 {len(all_edges())} 本 / 未通過 {len(uncovered_transitions(traj))} 本")
check("違反0件の道を通すと未通過が減る",
      len(uncovered_transitions(clean_traj)) == 13
      and "wrapping_up --> done: reported" not in uncovered_transitions(clean_traj),
      f"未通過 {len(uncovered_transitions(clean_traj))} 本")

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション6の検証はすべて成功しました。")
