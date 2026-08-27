#!/usr/bin/env python3
"""復習01（S02〜S05）の自己検証。

    docker compose exec app python src/review01/verify.py

10問すべてを機械判定する。1つでも満たさなければ非0で終了するので、
出力を読んで「合っている気がする」と判断する余地はない。
本文・解答章に載せた数値もここで固定している（数値が変わったら本文を直す）。
"""

from __future__ import annotations

import sys

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.models import Step, ToolCall, ToolResult, Trajectory  # noqa: E402

from failure_modes import classify  # noqa: E402  (src/session02)

import answers  # noqa: E402
import traces  # noqa: E402
import triage  # noqa: E402
from batch import plan_batches, render_batches  # noqa: E402
from diagnose import diagnose, is_trustworthy_done, untrusted_reasons  # noqa: E402
from plan import REVIEW_PLAN, Plan, SubGoal, should_replan, trailing_failures  # noqa: E402
from report import diagnose_report  # noqa: E402
from sideeffects import run_pair  # noqa: E402
from tokens import history_tokens  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


cases = traces.by_label()

# ---------------------------------------------------------------------------
# 材料：6本の軌跡が期待どおりの形をしていること
# ---------------------------------------------------------------------------
print("=== 材料（6本の軌跡） ===")
SHAPE = {
    #                停止理由      手数 呼び出し 成功 失敗
    "A_normal": ("done", 4, 3, 3, 0),
    "B_stuck_loop": ("max_steps", 6, 6, 6, 0),
    "C_rephrase_loop": ("max_steps", 4, 4, 0, 4),
    "D_false_report": ("done", 3, 2, 2, 0),
    "E_under_limit": ("max_steps", 3, 3, 3, 0),
    "F_actionable_loop": ("max_steps", 4, 4, 0, 4),
}
for label, expected in SHAPE.items():
    traj = cases[label].traj
    results = [r for step in traj.steps for r in step.results]
    got = (traj.stop_reason, len(traj.steps), len(traj.tool_names),
           sum(1 for r in results if r.ok), sum(1 for r in results if not r.ok))
    check(f"軌跡 {label} の形が期待どおり", got == expected, str(got))

tokens_a = [step.usage.get("input_tokens", 0) for step in cases["A_normal"].traj.steps]
check("入力トークンはステップごとに増える（履歴が毎回全部送られる）",
      all(a < b for a, b in zip(tokens_a, tokens_a[1:])), str(tokens_a))

# ---------------------------------------------------------------------------
# 問題1：停止理由と失敗モード
# ---------------------------------------------------------------------------
print("\n=== 問題1：停止理由と失敗モード ===")
MODES = {
    "A_normal": [],
    "B_stuck_loop": ["暴走", "停滞"],
    "C_rephrase_loop": ["暴走"],
    "D_false_report": ["誤選択", "幻覚", "権限逸脱"],
}
for label, expected in MODES.items():
    case = cases[label]
    got = classify(case.traj, allowed_tools=set(case.allowed), registry=case.registry)
    check(f"{label} の失敗モードが期待どおり", got == expected, str(got))
    check(f"問題1 の解答（{label}）",
          answers.Q1.get(label) == (case.traj.stop_reason, got),
          str(answers.Q1.get(label)))
c_args = [call.args["instruction"]
          for step in cases["C_rephrase_loop"].traj.steps for call in step.calls]
check("言い方を変えて叩くループは「停滞」では捕まらない（引数が毎回違う）",
      len(set(c_args)) == 4 and "停滞" not in MODES["C_rephrase_loop"],
      f"異なる引数 {len(set(c_args))} 種")

# ---------------------------------------------------------------------------
# 問題2：3択と上限設計
# ---------------------------------------------------------------------------
print("\n=== 問題2：3択と上限設計 ===")
truth = triage.truth()
for name, row in truth.items():
    answer = answers.Q2.get(name) or {}
    same = (answer.get("choice") == row["choice"]
            and answer.get("max_steps") == row.get("max_steps")
            and answer.get("on_limit") == row.get("on_limit"))
    check(f"問題2 の解答（{name} → {row['choice']}）", same, str(answer))
check("エージェントを選んだ要求には必ずステップ上限が付く",
      all("ステップ上限" in row["guardrails"]
          for row in truth.values() if row["choice"] == "エージェント"))
check("取り返しのつかない操作には承認ゲートが付く",
      "承認ゲート" in truth["取引先への謝罪文送付"]["guardrails"])
check("上限は深さ＋余裕2＋報告1で決まる（4 → 7）",
      truth["監査指摘の洗い出し"]["max_steps"] == 7)
check("副作用があるものは上限到達時に人間へ渡す",
      truth["取引先への謝罪文送付"]["on_limit"] == "handoff")

# ---------------------------------------------------------------------------
# 問題3：並列にしてよい塊を決める
# ---------------------------------------------------------------------------
print("\n=== 問題3：並列と直列の切り分け ===")
registry = build_registry()


def make_calls(*names: str) -> list:
    return [ToolCall(f"c{i}", name, {}) for i, name in enumerate(names)]


def shape(*names: str) -> list:
    return [(mode, [call.name for call in group])
            for mode, group in plan_batches(registry, make_calls(*names))]


check("読み取り3本は1つの並列バッチになる",
      shape("get_policy", "list_expenses", "search_docs")
      == [("parallel", ["get_policy", "list_expenses", "search_docs"])],
      render_batches(plan_batches(registry, make_calls("get_policy", "list_expenses",
                                                       "search_docs"))))
check("読み取り2本＋書き込みは並列1つと直列1つ",
      shape("get_policy", "list_expenses", "write_file")
      == [("parallel", ["get_policy", "list_expenses"]), ("serial", ["write_file"])])
check("書き込みが挟まると読み取りもまとめられない",
      shape("get_policy", "write_file", "list_expenses")
      == [("serial", ["get_policy"]), ("serial", ["write_file"]),
          ("serial", ["list_expenses"])])
check("承認が必要な送信は単独の直列になる",
      shape("search_docs", "send_message")
      == [("serial", ["search_docs"]), ("serial", ["send_message"])])
check("未登録のツールは直列に落とす",
      shape("no_such_tool") == [("serial", ["no_such_tool"])])
check("読み取り1本だけなら並列とは呼ばない",
      shape("get_policy") == [("serial", ["get_policy"])])

# ---------------------------------------------------------------------------
# 問題4：ツール結果の大きさが履歴に積み上がる
# ---------------------------------------------------------------------------
print("\n=== 問題4：結果の大きさと履歴の累積 ===")
big = history_tokens([1038, 1038, 1038])
small = history_tokens([102, 102, 102])
check("全件を返す道具の履歴（近似トークン）", big == [10, 356, 702, 1048], str(big))
check("絞って返す道具の履歴（近似トークン）", small == [10, 44, 78, 112], str(small))
check("合計は 2,116 と 244", (sum(big), sum(small)) == (2116, 244),
      f"{sum(big)} / {sum(small)}")
check("同じ手数でも約8.7倍の差が出る", round(sum(big) / sum(small), 1) == 8.7,
      f"{sum(big) / sum(small):.2f}")
check("負の文字数は受け付けない", raises_value_error(lambda: history_tokens([-1])))

# ---------------------------------------------------------------------------
# 問題5：原因の切り分け
# ---------------------------------------------------------------------------
print("\n=== 問題5：症状から原因へ ===")
CAUSE_TRUTH = {
    "A_normal": [],
    "B_stuck_loop": ["計画がない"],
    "C_rephrase_loop": ["道具のエラーが不親切", "道具の粒度が粗い"],
    "D_false_report": ["報告が実態と違う"],
    "E_under_limit": ["上限不足"],
    "F_actionable_loop": ["モデルが直せない"],
}
for label, expected in CAUSE_TRUTH.items():
    case = cases[label]
    got = diagnose(case.traj, registry=case.registry,
                   allowed_tools=case.allowed, needed_steps=case.needed_steps)
    check(f"{label} の原因が期待どおり", got == expected, str(got))

case_b = cases["B_stuck_loop"]
check("同じ症状（max_steps）でも原因は同じではない",
      diagnose(case_b.traj, registry=case_b.registry, allowed_tools=case_b.allowed,
               needed_steps=2)
      != diagnose(cases["E_under_limit"].traj, registry=cases["E_under_limit"].registry,
                  allowed_tools=cases["E_under_limit"].allowed, needed_steps=4))
check("上限だけを上げても直らない軌跡がある（B は 12 手用意しても止まらない）",
      len(traces._run(traces.STUCK_LOOP, build_registry(), traces.POLICY_TASK,
                      max_steps=10, task_id="TASK-R01-B10").steps) == 10)

# ---------------------------------------------------------------------------
# 問題6：done を信用してよいか
# ---------------------------------------------------------------------------
print("\n=== 問題6：done の裏取り ===")


def trust(label: str) -> bool:
    case = cases[label]
    return is_trustworthy_done(case.traj, registry=case.registry,
                               allowed_tools=case.allowed)


def reasons(label: str) -> list[str]:
    case = cases[label]
    return untrusted_reasons(case.traj, registry=case.registry,
                             allowed_tools=case.allowed)


check("正常系の最終回答は信用してよい", trust("A_normal"))
check("嘘の完了報告は信用できない", not trust("D_false_report"))
check("嘘の理由に幻覚と権限逸脱が並ぶ",
      "失敗モード: 幻覚" in reasons("D_false_report")
      and "失敗モード: 権限逸脱" in reasons("D_false_report"),
      str(reasons("D_false_report")))
check("打ち切られた軌跡は停止理由と空の最終回答の両方が理由になる",
      reasons("B_stuck_loop") == ["停止理由が done ではない（max_steps）", "最終回答が空",
                                 "失敗モード: 暴走", "失敗モード: 停滞"],
      str(reasons("B_stuck_loop")))
check("上限で止まった軌跡は理由が4件立つ", len(reasons("F_actionable_loop")) == 4,
      str(reasons("F_actionable_loop")))

# ---------------------------------------------------------------------------
# 問題7：軌跡が同じでも副作用は同じではない
# ---------------------------------------------------------------------------
print("\n=== 問題7：軌跡が同じでも残るものは違う ===")
pair = run_pair()
UNCHECKED = {"steps": 3, "tools": ["submit_expense", "submit_expense"], "ok_calls": 2,
             "stop_reason": "done", "added": 2,
             "categories": ["打ち上げ", "接待交際費"], "modes": ["権限逸脱"]}
CHECKED = {"steps": 3, "tools": ["submit_expense", "submit_expense"], "ok_calls": 1,
           "stop_reason": "done", "added": 1,
           "categories": ["接待交際費"], "modes": ["権限逸脱"]}
check("検証なしは2件登録され、列挙外の区分が残る", pair["検証なし"] == UNCHECKED,
      str(pair["検証なし"]))
check("検証ありは1件だけ登録される", pair["検証あり"] == CHECKED, str(pair["検証あり"]))
check("手数・停止理由・失敗モードは一致する",
      (pair["検証なし"]["steps"], pair["検証なし"]["stop_reason"], pair["検証なし"]["modes"])
      == (pair["検証あり"]["steps"], pair["検証あり"]["stop_reason"],
          pair["検証あり"]["modes"]))
check("違いは残ったデータにしか出ない",
      pair["検証なし"]["added"] != pair["検証あり"]["added"])

# ---------------------------------------------------------------------------
# 問題8：計画の DAG と再計画のトリガ
# ---------------------------------------------------------------------------
print("\n=== 問題8：計画と再計画 ===")
check("実行順が依存関係から決まる（同順位は辞書順）",
      REVIEW_PLAN.order() == ["expenses", "policy", "check", "report"],
      str(REVIEW_PLAN.order()))
check("いま着手できるのは依存のない2つ",
      REVIEW_PLAN.next_ready(set()) == ["expenses", "policy"])
check("2つ済めば check が着手できる",
      REVIEW_PLAN.next_ready({"policy", "expenses"}) == ["check"])
check("残り手数が数えられる", REVIEW_PLAN.remaining_steps({"policy", "expenses"}) == 2)
check("循環している計画はエラーになる",
      raises_value_error(lambda: Plan("循環", [SubGoal("a", "get_policy", ("b",)),
                                              SubGoal("b", "get_policy", ("a",))]).order()))
check("存在しない依存はエラーになる",
      raises_value_error(lambda: Plan("欠け", [SubGoal("a", "get_policy", ("z",))]).order()))

count, name = trailing_failures(cases["C_rephrase_loop"].traj)
check("末尾の連続失敗を数えられる", (count, name) == (4, "manage_expense"),
      f"{count} / {name}")

replan_c, why_c = should_replan(cases["C_rephrase_loop"].traj, REVIEW_PLAN,
                               done=set(), max_steps=4)
check("同じ道具で2回以上続けて失敗したら再計画", replan_c and "2回以上" in why_c, why_c)

broken = Trajectory(task_id="TASK-R01-X", task=REVIEW_PLAN.task)
broken.steps.append(Step(0, "規程を読む",
                         [ToolCall("x0", "get_policy", {"topic": "接待費"})],
                         [ToolResult("x0", False, "",
                                     "'接待費' の規程は見つかりません。"
                                     "指定できる項目: 経費精算, 接待交際費。")],
                         {}))
replan_x, why_x = should_replan(broken, REVIEW_PLAN, done=set(), max_steps=8)
check("前提が崩れたら（1回の失敗でも）再計画", replan_x and "前提が崩れた" in why_x, why_x)

replan_b, why_b = should_replan(cases["B_stuck_loop"].traj, REVIEW_PLAN,
                                done=set(), max_steps=6)
check("残り手数が計画に足りなければ再計画", replan_b and "残り手数" in why_b, why_b)
check("余裕があれば計画どおり進める",
      not should_replan(cases["B_stuck_loop"].traj, REVIEW_PLAN,
                        done=set(), max_steps=20)[0])
check("計画が終わっていれば再計画しない",
      not should_replan(cases["A_normal"].traj, REVIEW_PLAN,
                        done=set(REVIEW_PLAN.keys()), max_steps=8)[0])

# ---------------------------------------------------------------------------
# 問題9：診断レポート
# ---------------------------------------------------------------------------
print("\n=== 問題9：診断レポートの生成 ===")
report_c = diagnose_report(cases["C_rephrase_loop"])
for line in ("### C_rephrase_loop",
             "- 症状: 停止理由 max_steps / 手数 4 / ツール呼び出し 4",
             "- 失敗モード: 暴走",
             "- 原因: 道具のエラーが不親切, 道具の粒度が粗い",
             "- 手当て: S04（エラーに許容値と次の一手を書く）, "
             "S04（自由文字列1引数をやめてスキーマで縛る）"):
    check(f"レポートに「{line[:26]}」が出る", line in report_c)

report_a = diagnose_report(cases["A_normal"])
check("正常系は「異常なし」と「信用してよい」になる",
      "- 原因: 異常なし" in report_a and "信用してよい（裏取りできた）" in report_a,
      report_a.splitlines()[-1])
check("レポートは必ず5行の項目を持つ",
      all(len(diagnose_report(case).splitlines()) == 6 for case in cases.values()))

# ---------------------------------------------------------------------------
# 問題10（実践・任意）：障害報告の切り分けと runbook
# ---------------------------------------------------------------------------
print("\n=== 問題10：障害報告の切り分け（実践・任意） ===")
INCIDENTS = {
    "INC-01": {"causes": ["計画がない"], "first": "S05"},
    "INC-02": {"causes": ["道具のエラーが不親切", "道具の粒度が粗い"], "first": "S04"},
    "INC-03": {"causes": ["上限不足"], "first": "S03"},
    "INC-04": {"causes": ["報告が実態と違う"], "first": "S02"},
}
for incident, expected in INCIDENTS.items():
    check(f"問題10 の解答（{incident}）", answers.Q10.get(incident) == expected,
          str(answers.Q10.get(incident)))

runbook = ROOT / "workspace" / "review01_runbook.md"
if runbook.exists():
    text = runbook.read_text(encoding="utf-8")
    missing = [heading for heading in ("## 症状", "## 切り分け", "## 手当て", "## 再発防止")
               if heading not in text]
    check("runbook に4つの節がそろっている", not missing, str(missing))
else:
    print("SKIP workspace/review01_runbook.md が無いため runbook の検査を飛ばします")

# ---------------------------------------------------------------------------
traces.reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習01の検証はすべて成功しました。")
