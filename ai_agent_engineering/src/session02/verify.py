#!/usr/bin/env python3
"""セッション2の自己検証：ワークフローとエージェントの違いを数字で固定する。

本文に載せた数値（LLM 呼び出し回数・手数・近似トークン・失敗モード）は、
この検証が保証している。数値が変わったら本文を直す必要がある、という関係を
テストの形で残すのが目的である。

  python src/session02/verify.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import agent_book_room as agent_side  # noqa: E402
import decision  # noqa: E402
import failure_modes as fm  # noqa: E402
import workflow_book_room as wf  # noqa: E402
import workflow_report as wr  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def reset_data() -> None:
    """演習で汚れたデータを初期状態に戻す（決定的に再生成される）。"""
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


reset_data()

# --- 1. ワークフロー版：制御は人間側にあり、LLM を1回も呼ばない --------------
fixed = wf.book_fixed("みなと", "10:00")
check("分岐なしのワークフローは競合で行き止まりになる", not fixed.ok, fixed.message)
check("失敗しても LLM を呼んでいない", fixed.llm_calls == 0)
check("ツール呼び出しは1回だけ", len(fixed.tool_calls) == 1, str(fixed.tool_calls))

fallback = wf.book_with_fallback("みなと", ["10:00", "11:00"])
check("候補を列挙したワークフローは成功する", fallback.ok, fallback.message)
check("成功しても LLM 呼び出しは0回", fallback.llm_calls == 0)
check("ツール呼び出しは2回", len(fallback.tool_calls) == 2, str(fallback.tool_calls))
check("11:00 に切り替わっている", "11:00" in fallback.message)

# --- 2. エージェント版：同じ結果に、3回の LLM 呼び出しで到達する -------------
traj = agent_side.run_conflict_retry()
check("エージェント版も完了する", traj.stop_reason == "done", f"stop_reason={traj.stop_reason}")
check("手数は3（1ステップ＝1回の LLM 呼び出し）", len(traj.steps) == 3, f"steps={len(traj.steps)}")
check("ツール呼び出しは book_room が2回",
      traj.tool_names == ["book_room", "book_room"], str(traj.tool_names))
check("11:00 に切り替えて完了している", "11:00" in (traj.final or ""), (traj.final or "")[:40])

tokens = traj.total_tokens
check("近似入力トークンが tools/traj_stats.py の記録値と一致する（本文の 436）",
      tokens["input"] == 436, str(tokens))
check("近似出力トークンが記録値と一致する（本文の 35）", tokens["output"] == 35, str(tokens))
check("同じ結果に対する LLM 呼び出しは 0 回 対 3 回",
      fallback.llm_calls == 0 and len(traj.steps) == 3)

# --- 3. 決定性：2回走らせても同じ軌跡になる ---------------------------------
traj_again = agent_side.run_conflict_retry()
check("2回実行して軌跡が一致する",
      traj.tool_names == traj_again.tool_names and traj.final == traj_again.final)
check("2回実行して近似トークンも一致する",
      traj.total_tokens == traj_again.total_tokens)

# --- 4. 経路が固定できない要求では、固定した経路が行き止まりになる -----------
naive = wf.book_fixed("大会議室", "13:00")
check("固定した経路（大会議室 13:00）は競合で失敗する", not naive.ok, naive.message)
check("エラーメッセージが次の手の手がかりを含む", "別の会議室" in naive.message)

capacity = agent_side.run_capacity()
check("エージェントは実行時に別室へ切り替えて完了する",
      capacity.stop_reason == "done", f"stop_reason={capacity.stop_reason}")
check("切り替え先が定員10名以上の部屋（みなと・定員12名）",
      "みなと" in (capacity.final or ""), (capacity.final or "")[:40])
check("手数は4・ツール呼び出しは3",
      len(capacity.steps) == 4 and len(capacity.tool_names) == 3,
      f"steps={len(capacity.steps)} tools={capacity.tool_names}")
check("エージェントのほうが LLM 呼び出しが多い（0 対 4）",
      naive.llm_calls == 0 and len(capacity.steps) == 4)

# --- 5. 失敗モードの分類 ----------------------------------------------------
modes = {label: found for label, _traj, found in fm.run_cases()}
check("正常系では失敗モードを検出しない",
      modes["expense_report（正常系）"] == [], str(modes["expense_report（正常系）"]))
check("上限に張り付く軌跡は暴走と停滞",
      modes["max_steps_loop"] == ["暴走", "停滞"], str(modes["max_steps_loop"]))
check("道具を誤って嘘の報告をする軌跡は誤選択・幻覚・権限逸脱",
      modes["s02_wrong_tool"] == ["誤選択", "幻覚", "権限逸脱"], str(modes["s02_wrong_tool"]))
check("注入に従った軌跡は誤選択と権限逸脱",
      modes["injection_naive"] == ["誤選択", "権限逸脱"], str(modes["injection_naive"]))

# --- 6. 3択の判定 -----------------------------------------------------------
EXPECTED_CHOICES = {
    "経費の分類": decision.SINGLE_CALL,
    "会議室の予約": decision.WORKFLOW,
    "問い合わせの一次回答": decision.SINGLE_CALL,
    "月次レポート作成": decision.WORKFLOW,
    "規程改定の影響調査": decision.AGENT,
}
for request in decision.REQUESTS:
    result = decision.choose(request)
    check(f"3択の判定: {request.name} → {EXPECTED_CHOICES[request.name]}",
          result.choice == EXPECTED_CHOICES[request.name], result.choice)

agent_requests = [r for r in decision.REQUESTS if decision.choose(r).choice == decision.AGENT]
check("エージェントを選んだ要求には必ずステップ上限を付ける",
      all("ステップ上限" in decision.choose(r).guardrails for r in agent_requests),
      f"{len(agent_requests)} 件")

risky = decision.Request("送信まで行う調査", path_fixed=False, needs_judgment=True, steps=0,
                         failure_tolerance="low", irreversible=True, audit="strict")
risky_guards = decision.choose(risky).guardrails
check("取り返しのつかない操作を含むなら承認ゲートを足す", "承認ゲート" in risky_guards,
      " / ".join(risky_guards))

# --- 7. ワークフロー版のレポートがエージェント版と同じ数値に到達する ---------
reset_data()
report = wr.build_report(wr.load_expenses())
check("合計が 285,400円", "- 合計: 285,400円" in report)
check("却下済み（EXP-0005）は注記に含めない", "EXP-0005" not in report)
check("EXP-0002 と EXP-0004 を注記する", "EXP-0002" in report and "EXP-0004" in report)

scenario_path = ROOT / "scenarios" / "expense_report.json"
agent_report = json.loads(scenario_path.read_text(encoding="utf-8"))
agent_body = agent_report["turns"][2]["calls"][0]["args"]["content"]
same_numbers = ["- 交通費: 7,600円", "- 接待交際費: 120,000円",
                "- 備品: 12,800円", "- 出張旅費: 145,000円"]
check("エージェント版と同じ数値に到達している",
      all(line in report and line in agent_body for line in same_numbers))

reset_data()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション2の検証はすべて成功しました。")
