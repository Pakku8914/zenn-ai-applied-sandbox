#!/usr/bin/env python3
"""セッション10の自己検証：承認ゲートが主張どおりに動くこと。

本文（body / practice / solutions）に載せた出力・数値をここで検証している。
数値が変わる変更をしたときは、NG 行に出る実測値に合わせて本文を直すこと。
副作用（経費の追加・メッセージ送信）を出すので、各節の前後で `tools/make_data.py`
を実行してデータを初期状態に戻す。

    python src/session10/verify.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json  # noqa: E402

from agentkit.approval import call_digest  # noqa: E402
from agentkit.biztools import DATA, build_registry  # noqa: E402
from agentkit.clock import JST, FixedClock  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.models import STOP_REASONS, ToolCall  # noqa: E402
from approval_runner import (ApprovalRunner, inflate_amount, llm_calls,  # noqa: E402
                             render_run)
from approval_scenarios import (ALTERNATIVE, CONDITIONAL, DUAL_SEND,  # noqa: E402
                                EXPENSE_APPROVAL, PII_SEND, SMALL_EXPENSE,
                                TASK, TASK_LEAK, TASK_SEND, TASK_SMALL)
from audit import AuditLog, rewrite_rows, tamper  # noqa: E402
from gap import (TrustingGate, blanket_approval, drift_at_gate,  # noqa: E402
                 naive_resume_bug, naive_stop)
from gate import ReviewGate  # noqa: E402
from policy import (decide, escalate, expense_key, matrix_table,  # noqa: E402
                    relax, survey)

DIR = ROOT / "traces" / "checkpoints" / "session10_verify"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# ---------------------------------------------------------------------------
# 補助
# ---------------------------------------------------------------------------
def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def fresh_dir(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)


def rows_of(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def expense_rows() -> int:
    return len(rows_of("expenses"))


def last_expense() -> dict:
    rows = rows_of("expenses")
    return rows[-1] if rows else {}


def message_rows() -> int:
    return len(rows_of("messages"))


def new_gate(task_id: str, clock=None) -> ReviewGate:
    gate = ReviewGate(task_id, clock=clock)
    gate.audit.reset()
    return gate


def new_runner(scenario, gate, *, task_id: str, **kwargs) -> ApprovalRunner:
    return ApprovalRunner(ScriptedClient(scenario), build_registry(), gate,
                          task_id=task_id, checkpoint_dir=DIR, **kwargs)


def snapshot(task_id: str) -> None:
    for suffix in (".traj.jsonl", ".state.json"):
        shutil.copy2(DIR / f"{task_id}{suffix}", DIR / f"{task_id}{suffix}.bak")


def restore(task_id: str) -> None:
    for suffix in (".traj.jsonl", ".state.json"):
        shutil.copy2(DIR / f"{task_id}{suffix}.bak", DIR / f"{task_id}{suffix}")


# ---------------------------------------------------------------------------
# 本文に載せた期待出力
# ---------------------------------------------------------------------------
MATRIX_TABLE = """| 可逆性＼影響範囲 | 自分の作業領域 | 社内 | 社外 |
| :--- | :--- | :--- | :--- |
| 取り消せる | 自動実行 | 自動実行 | 事前承認 |
| 取り消せるが痕跡が残る | 自動実行 | 事後通知 | 事前承認 |
| 取り消せない | 事後通知 | 事前承認 | 二重承認 |"""

EXPECTED_STOP = """task_id=TASK-010 stop_reason=awaiting_approval 手数=2
  step 0 <running> get_policy:ok [auto] -> executed
  step 1 <awaiting_approval> submit_expense:待ち [approve] -> awaiting
  final: None"""

EXPECTED_DONE = """task_id=TASK-010 stop_reason=done 手数=3
  step 0 <running> get_policy:ok [auto] -> executed
  step 1 <resumed> submit_expense:ok [approve] -> executed
  step 2 <running> （ツールなし） -> done
  final: 接待交際費 68,000 円の申請を登録しました。5万円以上のため事前承認を得ています。"""

REQUEST_LINES = [
    "【承認依頼】submit_expense",
    "  - amount: 68000",
    "  - category: 接待交際費",
    "  - employee: 高橋 涼",
    "  - idempotency_key: 2026-08-15-EMP-003-68000",
    "  - note: 取引先との打ち合わせ",
    "※ 実行時にこのハッシュが一致することを確認します",
    "■ 判定: 事前承認（必要な承認者 1 名）",
    "  - 取り消せない × 社内 → 事前承認（取り下げには承認者の手間がかかる）",
    "  - 金額 68,000 円 ≧ 基準 50,000 円（規程「経費精算」: 1件5万円以上は事前承認が必要）",
    "  - 経費申請: 6 件 / 285,400 円 → 7 件 / 353,400 円",
    "  - 追加される行: 高橋 涼 / 68,000 円 / 接待交際費",
    "  - 取り下げには承認者の操作が必要です（自動では戻せません）",
    "■ ここまでに参照した情報（根拠）",
    "  - get_policy",
    "■ 期限: 2026-08-16T09:00:00+09:00（24 時間）",
]

EXPECTED_SMALL = """task_id=TASK-010-SMALL stop_reason=done 手数=2
  step 0 <running> submit_expense:ok [notify] -> executed
  step 1 <running> （ツールなし） -> done
  final: 交通費 3,200 円の申請を登録しました（基準額未満のため事後通知です）。"""

ALTERNATIVE_FINAL = ("申請は実行していません。下書きを workspace/session10/expense_draft.md に"
                     "残したので、承認の可否を確認のうえ手で申請してください。")

EXPECTED_REJECT = f"""task_id=TASK-010-REJ stop_reason=done 手数=3
  step 0 <resumed> submit_expense:NG [approve] -> rejected
  step 1 <running> write_file:ok [auto] -> executed
  step 2 <running> （ツールなし） -> done
  final: {ALTERNATIVE_FINAL}"""

EXPECTED_ABORT = """task_id=TASK-010-ABORT stop_reason=error 手数=1
  step 0 <resumed> send_message:NG [dual] -> rejected
  final: 承認されなかったため中止しました。理由: 社外への個人情報の送信は規程違反です"""

EXPECTED_COND = """task_id=TASK-010-COND stop_reason=done 手数=2
  step 0 <resumed> submit_expense:ok [approve] -> executed
  step 1 <running> （ツールなし） -> done
  final: 接待交際費の申請を登録しました（承認者の修正により 48,000 円）。"""

EXPECTED_EXPIRED = f"""task_id=TASK-010-EXP stop_reason=done 手数=3
  step 0 <resumed> submit_expense:NG [approve] -> expired
  step 1 <running> write_file:ok [auto] -> executed
  step 2 <running> （ツールなし） -> done
  final: {ALTERNATIVE_FINAL}"""

EXPECTED_DUAL = """task_id=TASK-010-DUAL stop_reason=done 手数=2
  step 0 <resumed> send_message:ok [dual] -> executed
  step 1 <running> （ツールなし） -> done
  final: 取引先へ送付完了の連絡を送りました（社外宛のため二者承認を得ています）。"""


# ---------------------------------------------------------------------------
# 1. 止める基準（判定表）
# ---------------------------------------------------------------------------
print("--- 1. 止める基準 ---")
check("可逆性 × 影響範囲のマトリクスが本文の表と一致する",
      matrix_table() == MATRIX_TABLE, "\n" + matrix_table())
check("代表的な9操作の判定が本文の表と一致する",
      [r["mode"] for r in survey()]
      == ["auto", "auto", "notify", "notify", "approve", "approve",
          "dual", "dual", "approve"],
      str([(r["ツール"], r["mode"]) for r in survey()]))
check("引き上げは厳しい方・引き下げは緩い方を採る",
      escalate("notify", "approve") == "approve" and escalate("dual", "notify") == "dual"
      and relax("approve", "notify") == "notify" and relax("auto", "dual") == "auto")
check("同じツールでも金額で段階が変わる",
      decide(ToolCall("a", "submit_expense", {"amount": 49_999})).mode == "notify"
      and decide(ToolCall("a", "submit_expense", {"amount": 50_000})).mode == "approve")
check("未登録の操作は止める側に倒す",
      decide(ToolCall("a", "drop_table", {})).mode == "approve")
check("冪等キーは 日付-社員ID-金額（セッション4の規約）",
      expense_key("EMP-003", 68_000) == "2026-08-15-EMP-003-68000")

same_a = ToolCall("x1", "submit_expense", {"amount": 68_000, "employee": "高橋 涼"})
same_b = ToolCall("x2", "submit_expense", {"employee": "高橋 涼", "amount": 68_000})
other = ToolCall("x3", "submit_expense", {"amount": 68_001, "employee": "高橋 涼"})
check("照合ハッシュは16桁で、引数の順序には依存しない",
      len(call_digest(same_a)) == 16 and call_digest(same_a) == call_digest(same_b))
check("1円違えば別のハッシュになる", call_digest(same_a) != call_digest(other))
check("awaiting_approval は agentkit が最初から持っている停止理由",
      "awaiting_approval" in STOP_REASONS)

# ---------------------------------------------------------------------------
# 2. 素の agentkit に足りないもの
# ---------------------------------------------------------------------------
print("\n--- 2. 素の agentkit に足りないもの ---")
stop_result = naive_stop()
check("素の ReActAgent でも承認待ちで止まれる",
      stop_result == {"stop_reason": "awaiting_approval", "ステップ数": 2,
                      "止まった操作": "submit_expense",
                      "そのステップのツール結果の数": 0, "expenses の行数": 6},
      str(stop_result))

bug = naive_resume_bug()
check("素の再開では、承認した操作が実行されないまま done になる",
      bug["承認したか"] and bug["stop_reason"] == "done"
      and bug["承認した操作のツール結果の数"] == 0 and bug["expenses の行数"] == 6,
      str(bug))
check("しかもモデルは「登録しました」と報告する",
      "登録しました" in (bug["最終回答"] or ""), str(bug["最終回答"]))

blanket = blanket_approval()
check("ツール単位の判定では 3,200 円の申請でも止まってしまう",
      blanket["ツール単位の判定（agentkit の既定）"] == "awaiting_approval"
      and blanket["止まった金額"] == 3_200
      and blanket["操作単位の判定（セッション10）"] == "notify",
      str(blanket))

drift = drift_at_gate()
check("ツール名で覚えるゲートは、承認していない金額を通してしまう",
      drift["ツール名で覚える実装の判定"] is True
      and drift["ハッシュで固定する実装の判定"] is None
      and drift["引数の順序を変えても同じ判定"], str(drift))


# ---------------------------------------------------------------------------
# 3. 主役の流れ：中断 → 承認 → 再開
# ---------------------------------------------------------------------------
def main_flow(task_id: str = "TASK-010") -> dict:
    reset_data()
    fresh_dir(DIR)
    gate = new_gate(task_id)
    runner = new_runner(EXPENSE_APPROVAL, gate, task_id=task_id)
    stopped = runner.run(TASK)
    request = runner.pending_request()
    call = runner.pending_call()
    gate.approve(call, by="鈴木 彩", note="内容を確認。参加者名簿は後追いで提出させる")
    gate.save()
    resumed = new_runner(EXPENSE_APPROVAL, ReviewGate.load(task_id), task_id=task_id)
    done = resumed.run(TASK, resume=True)
    return {"stop": render_run(stopped), "done": render_run(done), "request": request,
            "audit": resumed.gate.audit, "手数": llm_calls(done),
            "rows": expense_rows(), "last": last_expense(),
            "approved_by": done.steps[1].usage.get("approved_by")}


print("\n--- 3. 中断 → 承認 → 再開 ---")
flow = main_flow()
check("承認待ちで中断した軌跡が本文と一致する", flow["stop"] == EXPECTED_STOP,
      "\n" + flow["stop"])
check("承認後に同じ状態から再開して完走する", flow["done"] == EXPECTED_DONE,
      "\n" + flow["done"])
check("承認を挟んでも手数は3手（再開でモデルに聞き直さない）", flow["手数"] == 3,
      str(flow["手数"]))
check("経費申請はちょうど1件増える",
      flow["rows"] == 7 and flow["last"]["expense_id"] == "EXP-0007"
      and flow["last"]["amount"] == 68_000,
      f"{flow['rows']} 行 / {flow['last'].get('expense_id')} / {flow['last'].get('amount')}")
check("誰が承認したかが軌跡に残る", flow["approved_by"] == ["鈴木 彩"],
      str(flow["approved_by"]))

missing = [line for line in REQUEST_LINES if line not in flow["request"]]
check("承認画面に必要な情報がすべて出ている", not missing, str(missing))
check("承認画面には照合用ハッシュが出る", "照合用ハッシュ: " in flow["request"])

audit_rows = flow["audit"].rows()
check("監査ログは3行（依頼・承認・実行）",
      [(r["event"], r["actor"]) for r in audit_rows]
      == [("requested", "agent"), ("approved", "鈴木 彩"), ("executed", "agent")],
      str([(r["event"], r["actor"]) for r in audit_rows]))
check("依頼の行に判定の根拠が残る",
      audit_rows[0]["detail"] == ("取り消せない × 社内 → 事前承認（取り下げには承認者の手間がかかる）; "
                                  "金額 68,000 円 ≧ 基準 50,000 円"
                                  "（規程「経費精算」: 1件5万円以上は事前承認が必要）"),
      audit_rows[0]["detail"])
check("承認の行に承認者と条件が残る",
      audit_rows[1]["detail"] == "1/1 内容を確認。参加者名簿は後追いで提出させる",
      audit_rows[1]["detail"])
check("実行の行に結果が残る", "EXP-0007 を申請しました" in audit_rows[2]["detail"],
      audit_rows[2]["detail"])
check("監査ログの鎖は健全", flow["audit"].verify_chain() == (True, -1),
      str(flow["audit"].verify_chain()))
check("読み取り（get_policy）は監査ログに書かない（軌跡に残る）",
      all(r["tool"] == "submit_expense" for r in audit_rows))

again = main_flow()
check("同じ手順を2回踏むと、まったく同じ軌跡と承認画面になる",
      again["stop"] == flow["stop"] and again["done"] == flow["done"]
      and again["request"] == flow["request"])

# ---------------------------------------------------------------------------
# 4. 基準額未満は止めない（事後通知）
# ---------------------------------------------------------------------------
print("\n--- 4. 基準額未満は止めない ---")
reset_data()
fresh_dir(DIR)
small_gate = new_gate("TASK-010-SMALL")
small = new_runner(SMALL_EXPENSE, small_gate, task_id="TASK-010-SMALL").run(TASK_SMALL)
check("3,200 円の申請は止まらずに完走する", render_run(small) == EXPECTED_SMALL,
      "\n" + render_run(small))
check("実行はされるが、記録は残る",
      expense_rows() == 7 and small_gate.audit.events() == ["notified"],
      f"{expense_rows()} 行 / {small_gate.audit.events()}")

reset_data()
fresh_dir(DIR)
loose = ReviewGate("TASK-010-LOOSE", threshold_yen=100_000)
loose.audit.reset()
through = new_runner(EXPENSE_APPROVAL, loose, task_id="TASK-010-LOOSE").run(TASK)
check("基準額を10万円に上げると 68,000 円は素通しになる（手数は3手のまま）",
      through.stop_reason == "done" and len(through.steps) == 3
      and llm_calls(through) == 3 and expense_rows() == 7
      and loose.audit.events() == ["notified"],
      f"{through.stop_reason} / {len(through.steps)} steps / 手数 {llm_calls(through)} / "
      f"{expense_rows()} 行 / {loose.audit.events()}")

# ---------------------------------------------------------------------------
# 5. 承認の二度押し
# ---------------------------------------------------------------------------
print("\n--- 5. 承認の二度押し ---")
reset_data()
fresh_dir(DIR)
twice_gate = new_gate("TASK-010-TWICE")
twice = new_runner(EXPENSE_APPROVAL, twice_gate, task_id="TASK-010-TWICE")
twice.run(TASK)
twice_gate.approve(twice.pending_call(), by="鈴木 彩")
twice_gate.save()
snapshot("TASK-010-TWICE")
first_resume = new_runner(EXPENSE_APPROVAL, ReviewGate.load("TASK-010-TWICE"),
                          task_id="TASK-010-TWICE").run(TASK, resume=True)
rows_after_first = expense_rows()
restore("TASK-010-TWICE")  # 承認画面が二度押された（同じ状態からもう一度再開する）
second_gate = ReviewGate.load("TASK-010-TWICE")
second_resume = new_runner(EXPENSE_APPROVAL, second_gate,
                           task_id="TASK-010-TWICE").run(TASK, resume=True)
check("1回目の再開で申請が1件増える",
      rows_after_first == 7 and first_resume.stop_reason == "done", f"{rows_after_first} 行")
check("二度押しでも申請は1件のまま", expense_rows() == 7, f"{expense_rows()} 行")
check("2回目は実行せず「済み」として扱う",
      second_resume.steps[1].usage["event"] == "already_done"
      and second_resume.stop_reason == "done",
      second_resume.steps[1].usage["event"])
check("監査ログに二度押しの痕跡が残る",
      second_gate.audit.events() == ["requested", "approved", "executed", "already_done"],
      str(second_gate.audit.events()))

# ---------------------------------------------------------------------------
# 6. 却下（代替案を出す / 中止する）
# ---------------------------------------------------------------------------
print("\n--- 6. 却下されたときの振る舞い ---")
reset_data()
fresh_dir(DIR)
rej_gate = new_gate("TASK-010-REJ")
rej = new_runner(ALTERNATIVE, rej_gate, task_id="TASK-010-REJ")
rej_stop = rej.run(TASK)
check("1手目で承認待ちになる",
      rej_stop.stop_reason == "awaiting_approval" and len(rej_stop.steps) == 1)
rej_gate.reject(rej.pending_call(), by="鈴木 彩",
                reason="接待の目的が確認できないので差し戻し")
rej_gate.save()
rej_done = new_runner(ALTERNATIVE, ReviewGate.load("TASK-010-REJ"),
                      task_id="TASK-010-REJ").run(TASK, resume=True)
check("却下されたら別の方法に切り替える", render_run(rej_done) == EXPECTED_REJECT,
      "\n" + render_run(rej_done))
check("却下の理由はツール結果としてモデルに渡る",
      "接待の目的が確認できないので差し戻し" in (rej_done.steps[0].results[0].error or ""),
      rej_done.steps[0].results[0].error or "")
check("却下されたので申請は増えていない", expense_rows() == 6, f"{expense_rows()} 行")
check("監査ログは依頼と却下の2行",
      rej_gate.audit.events() == ["requested", "rejected"], str(rej_gate.audit.events()))

reset_data()
fresh_dir(DIR)
abort_gate = new_gate("TASK-010-ABORT")
abort = new_runner(PII_SEND, abort_gate, task_id="TASK-010-ABORT", on_reject="abort")
abort_stop = abort.run(TASK_LEAK)
abort_call = abort.pending_call()
check("社外への個人情報の送信は二重承認になる",
      abort_stop.stop_reason == "awaiting_approval"
      and abort_stop.steps[0].usage["mode"] == "dual",
      abort_stop.steps[0].usage["mode"])
abort_gate.reject(abort_call, by="伊藤 蓮",
                  reason="社外への個人情報の送信は規程違反です")
abort_gate.save()
abort_done = new_runner(PII_SEND, ReviewGate.load("TASK-010-ABORT"),
                        task_id="TASK-010-ABORT",
                        on_reject="abort").run(TASK_LEAK, resume=True)
check("中止を選んだ場合は代替案を探さずに終わる",
      render_run(abort_done) == EXPECTED_ABORT, "\n" + render_run(abort_done))
check("メッセージは1件も送られていない", message_rows() == 0, f"{message_rows()} 行")
check("却下は1人で成立する（承認は2名必要でも、却下は1名で決まる）",
      abort_gate.required(call_digest(abort_call)) == 2
      and abort_gate.check(abort_call) is False,
      f"必要な承認者 {abort_gate.required(call_digest(abort_call))} 名 / "
      f"判定 {abort_gate.check(abort_call)}")

# ---------------------------------------------------------------------------
# 7. 条件付き承認
# ---------------------------------------------------------------------------
print("\n--- 7. 条件付き承認 ---")
reset_data()
fresh_dir(DIR)
cond_gate = new_gate("TASK-010-COND")
cond = new_runner(CONDITIONAL, cond_gate, task_id="TASK-010-COND")
cond.run(TASK)
original_call = cond.pending_call()
try:
    cond_gate.approve_with_changes(original_call, {"amount": 48_000}, by="鈴木 彩")
    guarded = False
    message = ""
except ValueError as exc:
    guarded = True
    message = str(exc)
check("金額だけ変えて承認しようとすると止められる",
      guarded and "idempotency_key" in message, message)
cond_gate.approve_with_changes(
    original_call,
    {"amount": 48_000, "idempotency_key": expense_key("EMP-003", 48_000)},
    by="鈴木 彩", note="上限内に収めるなら可")
cond_gate.save()
cond_done = new_runner(CONDITIONAL, ReviewGate.load("TASK-010-COND"),
                       task_id="TASK-010-COND").run(TASK, resume=True)
check("条件付き承認は書き換えた内容で実行される",
      render_run(cond_done) == EXPECTED_COND, "\n" + render_run(cond_done))
check("修正後の金額と冪等キーで登録される",
      last_expense().get("amount") == 48_000
      and last_expense().get("idempotency_key") == "2026-08-15-EMP-003-48000",
      f"{last_expense().get('amount')} / {last_expense().get('idempotency_key')}")
check("元の内容（68,000円）は承認されていないまま",
      cond_gate.check(original_call) is None, str(cond_gate.check(original_call)))
check("監査ログに条件付き承認と変更内容が残る",
      cond_gate.audit.events() == ["requested", "conditionally_approved", "executed"]
      and "amount: 68000 → 48000" in cond_gate.audit.rows()[1]["detail"],
      str(cond_gate.audit.events()) + " / " + cond_gate.audit.rows()[1]["detail"])

# ---------------------------------------------------------------------------
# 8. 承認されないまま放置された（タイムアウト）
# ---------------------------------------------------------------------------
print("\n--- 8. 承認のタイムアウト ---")
reset_data()
fresh_dir(DIR)
exp_gate = new_gate("TASK-010-EXP")
exp_runner = new_runner(ALTERNATIVE, exp_gate, task_id="TASK-010-EXP")
exp_runner.run(TASK)
exp_gate.save()

same_day = ReviewGate.load("TASK-010-EXP",
                           clock=FixedClock(datetime(2026, 8, 15, 18, 0, tzinfo=JST)))
still = new_runner(ALTERNATIVE, same_day, task_id="TASK-010-EXP").run(TASK, resume=True)
check("期限内なら承認待ちのまま（何度見に行っても同じ）",
      still.stop_reason == "awaiting_approval" and len(still.steps) == 1
      and same_day.audit.events() == ["requested"],
      f"{still.stop_reason} / {same_day.audit.events()}")

edge = ReviewGate.load("TASK-010-EXP",
                       clock=FixedClock(datetime(2026, 8, 16, 8, 59, tzinfo=JST)))
edge_traj = new_runner(ALTERNATIVE, edge, task_id="TASK-010-EXP").run(TASK, resume=True)
check("期限の1分前はまだ待つ（境界は比較演算子で決まる）",
      edge_traj.stop_reason == "awaiting_approval" and expense_rows() == 6,
      f"{edge_traj.stop_reason} / {expense_rows()} 行")

next_day = ReviewGate.load("TASK-010-EXP",
                           clock=FixedClock(datetime(2026, 8, 16, 10, 0, tzinfo=JST)))
expired = new_runner(ALTERNATIVE, next_day, task_id="TASK-010-EXP").run(TASK, resume=True)
check("期限を過ぎたら諦めて別の方法に切り替える",
      render_run(expired) == EXPECTED_EXPIRED, "\n" + render_run(expired))
check("期限切れでは申請は実行されない", expense_rows() == 6, f"{expense_rows()} 行")
check("監査ログに期限切れが残り、時刻は注入した時計の値になる",
      next_day.audit.events() == ["requested", "expired"]
      and next_day.audit.rows()[-1]["at"] == "2026-08-16T10:00:00+09:00",
      f"{next_day.audit.events()} / {next_day.audit.rows()[-1]['at']}")

# ---------------------------------------------------------------------------
# 9. 二重承認
# ---------------------------------------------------------------------------
print("\n--- 9. 二重承認 ---")
reset_data()
fresh_dir(DIR)
dual_gate = new_gate("TASK-010-DUAL")
dual = new_runner(DUAL_SEND, dual_gate, task_id="TASK-010-DUAL")
dual_stop = dual.run(TASK_SEND)
dual_call = dual.pending_call()
dual_digest = call_digest(dual_call)
check("社外宛の送信は承認者2名が必要",
      dual_stop.steps[0].usage["mode"] == "dual" and dual_gate.required(dual_digest) == 2,
      f"{dual_stop.steps[0].usage['mode']} / {dual_gate.required(dual_digest)}")
dual_gate.approve(dual_call, by="鈴木 彩", note="請求書の送付内容を確認")
dual_gate.approve(dual_call, by="鈴木 彩")  # 同じ人が2回押しても1票
check("同じ人が2回押しても1票",
      dual_gate.approvers_of(dual_digest) == ["鈴木 彩"]
      and dual_gate.check(dual_call) is None,
      str(dual_gate.approvers_of(dual_digest)))
dual_gate.save()
half = new_runner(DUAL_SEND, ReviewGate.load("TASK-010-DUAL"),
                  task_id="TASK-010-DUAL").run(TASK_SEND, resume=True)
check("1人目の承認だけでは実行されない",
      half.stop_reason == "awaiting_approval" and message_rows() == 0,
      f"{half.stop_reason} / {message_rows()} 行")
second_approver = ReviewGate.load("TASK-010-DUAL")
second_approver.approve(dual_call, by="伊藤 蓮", note="情報セキュリティ室として確認")
second_approver.save()
dual_done = new_runner(DUAL_SEND, ReviewGate.load("TASK-010-DUAL"),
                       task_id="TASK-010-DUAL").run(TASK_SEND, resume=True)
check("2人目が承認すると実行される", render_run(dual_done) == EXPECTED_DUAL,
      "\n" + render_run(dual_done))
check("送信は1件だけ", message_rows() == 1, f"{message_rows()} 行")
final_audit = AuditLog("TASK-010-DUAL")
check("監査ログに2人の承認者が並ぶ",
      [(r["event"], r["actor"]) for r in final_audit.rows()]
      == [("requested", "agent"), ("approved", "鈴木 彩"),
          ("approved", "伊藤 蓮"), ("executed", "agent")],
      str([(r["event"], r["actor"]) for r in final_audit.rows()]))
check("承認の行に何人目かが残る",
      final_audit.rows()[1]["detail"] == "1/2 請求書の送付内容を確認"
      and final_audit.rows()[2]["detail"] == "2/2 情報セキュリティ室として確認",
      final_audit.rows()[1]["detail"] + " / " + final_audit.rows()[2]["detail"])


# ---------------------------------------------------------------------------
# 10. 承認内容と実行内容がずれる
# ---------------------------------------------------------------------------
def drift_case(label: str, task_id: str, gate_cls, rewrite) -> dict:
    reset_data()
    fresh_dir(DIR)
    gate = gate_cls(task_id)
    gate.audit.reset()
    runner = new_runner(EXPENSE_APPROVAL, gate, task_id=task_id)
    runner.run(TASK)
    gate.approve(runner.pending_call(), by="鈴木 彩")
    gate.save()
    resumed = new_runner(EXPENSE_APPROVAL, gate_cls.load(task_id), task_id=task_id,
                         rewrite=rewrite)
    traj = resumed.run(TASK, resume=True)
    rows = expense_rows()
    return {"実装": label, "expenses の行数": rows,
            "実行された金額": last_expense().get("amount") if rows == 7 else "実行されない",
            "step 1 の決着": traj.steps[1].usage["event"],
            "監査ログ": resumed.gate.audit.events()}


print("\n--- 10. 承認内容と実行内容のずれ ---")
drift_rows = [
    drift_case("引数を組み立て直す × ツール名で覚える", "TASK-010-D1",
               TrustingGate, inflate_amount),
    drift_case("引数を組み立て直す × ハッシュで固定する", "TASK-010-D2",
               ReviewGate, inflate_amount),
    drift_case("組み立て直さない × ハッシュで固定する", "TASK-010-D3",
               ReviewGate, None),
]
for row in drift_rows:
    print(f"    {row['実装']}: {row['expenses の行数']} 行 / "
          f"金額 {row['実行された金額']} / {row['step 1 の決着']}")
check("ツール名で覚えるゲートは、承認していない 148,000 円を実行してしまう",
      drift_rows[0]["expenses の行数"] == 7
      and drift_rows[0]["実行された金額"] == 148_000
      and drift_rows[0]["step 1 の決着"] == "executed",
      str(drift_rows[0]))
check("ハッシュで固定すると実行前に止まる",
      drift_rows[1]["expenses の行数"] == 6
      and drift_rows[1]["step 1 の決着"] == "mismatch",
      str(drift_rows[1]))
check("ずれの記録が監査ログに残る",
      drift_rows[1]["監査ログ"] == ["requested", "approved", "rewritten", "mismatch"],
      str(drift_rows[1]["監査ログ"]))
check("組み立て直さなければ承認した内容がそのまま実行される",
      drift_rows[2]["expenses の行数"] == 7
      and drift_rows[2]["実行された金額"] == 68_000
      and drift_rows[2]["監査ログ"] == ["requested", "approved", "executed"],
      str(drift_rows[2]))

# ---------------------------------------------------------------------------
# 11. 監査ログの改ざん検出
# ---------------------------------------------------------------------------
print("\n--- 11. 監査ログの改ざん検出 ---")
log = AuditLog("TASK-010-TAMPER")
log.reset()
log.append("requested", tool="submit_expense", mode="approve", detail="金額 68,000 円")
log.append("approved", actor="鈴木 彩", tool="submit_expense", mode="approve", detail="1/1")
log.append("executed", tool="submit_expense", mode="approve", detail="EXP-0007")
check("鎖が健全なら (True, -1)", log.verify_chain() == (True, -1), str(log.verify_chain()))
intact = log.rows()
tamper(log, 1, "2/2 として承認されたことにする")
check("途中の1行を書き換えると検出できる", log.verify_chain() == (False, 1),
      str(log.verify_chain()))
check("行数は変わらない（消さずに検出する）", len(log.rows()) == 3, str(len(log.rows())))

rewrite_rows(log, [intact[0], intact[2]])  # 真ん中の行を消す
check("途中の行を削除すると検出できる", log.verify_chain() == (False, 1),
      str(log.verify_chain()))
rewrite_rows(log, [intact[0], intact[0], intact[1], intact[2]])  # 行を挿入する
check("行を挿入すると検出できる", log.verify_chain() == (False, 1),
      str(log.verify_chain()))
rewrite_rows(log, intact[:2])  # 末尾を切り落とす
check("末尾の切り落としは鎖だけでは検出できない（本文の注意点）",
      log.verify_chain() == (True, -1), str(log.verify_chain()))

# ---------------------------------------------------------------------------
reset_data()
fresh_dir(DIR)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション10の検証はすべて成功しました。")
