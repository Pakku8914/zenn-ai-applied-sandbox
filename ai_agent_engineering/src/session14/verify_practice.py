#!/usr/bin/env python3
"""セッション14 練習問題の合否判定。

    python src/session14/verify_practice.py

参照解（`ex_observe.py`）を呼んで判定する。自分の実装で判定したい場合は、
この import 元を自分のファイルに差し替えるだけでよい。1問でも落ちたら非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

from ex_observe import (grain_secrets, incident_report_missing, lookup_call,  # noqa: E402
                        masked_replay, replay_failure, root_steps, sampling_summary,
                        span_census, symptom_top, unit_flip, write_incident_report)
from redaction import FULL, FULL_MASKED, HASHED, SUMMARY  # noqa: E402
from spanlog import reset_data, run_case  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()

# --- 問題1 ------------------------------------------------------------------
cen = span_census()
check("問題1 スパンの階層を数えられる",
      cen["TASK-expense_report"]["total"] == 12
      and cen["TASK-max_steps_loop"]["total"] == 19
      and cen["TASK-max_steps_loop"]["tool"] == 6,
      f"expense_report={cen['TASK-expense_report']['total']} "
      f"max_steps_loop={cen['TASK-max_steps_loop']['total']}")

# --- 問題2 ------------------------------------------------------------------
look = lookup_call()
check("問題2 相関ID から1件を引ける",
      (look["hits"], look["name"], len(look["path"])) == (1, "write_file", 3),
      f"{look['span_id']}（{look['name']}）経路 {' → '.join(look['path'])}")

# --- 問題3 ------------------------------------------------------------------
grains = grain_secrets()
check("問題3 粒度ごとの機密の残り方を出せる",
      (grains[SUMMARY], grains[HASHED], grains[FULL], grains[FULL_MASKED]) == (0, 0, 2, 0),
      " / ".join(f"{k}={v}" for k, v in grains.items()))

# --- 問題4 ------------------------------------------------------------------
flip = unit_flip()
check("問題4 単価表を差し替えると内訳の1位が入れ替わる",
      (flip["A"], flip["B"], flip["A_total"], flip["B_total"]) == ("llm", "tool", 2060, 1100)
      and flip["steps"] == [520, 520, 520, 500]
      and flip["monotonic"] is True and flip["peak"] == 3,
      f"A の1位={flip['A']}（{flip['A_total']}ms） B の1位={flip['B']}（{flip['B_total']}ms）")

# --- 問題5 ------------------------------------------------------------------
roots = root_steps()
check("問題5 原因のステップを特定できる",
      roots == {"TASK-expense_report": "—",
                "TASK-book_room_conflict": "step[0]",
                "TASK-submit_expense_approval": "—",
                "TASK-injection_naive": "step[2]",
                "TASK-max_steps_loop": "step[2]",
                "TASK-expense_report-exception": "step[1]",
                "TASK-expense_report-empty": "step[1]",
                "TASK-expense_report-repeat": "step[2]"},
      f"打ち切りの原因={roots['TASK-max_steps_loop']} / "
      f"例外の原因={roots['TASK-expense_report-exception']}（軌跡に残っていないステップ）")

# --- 問題6 ------------------------------------------------------------------
rep = replay_failure()
check("問題6 記録した1件を再生できる",
      rep["cassette"] == 6
      and (rep["fixture_steps"], rep["fixture_stop"], rep["fixture_exc"]) == (1, "error", "KeyError")
      and (rep["replay_steps"], rep["replay_stop"]) == (6, "max_steps")
      and all(rep["flags"].values()),
      f"FixtureClient: 手数={rep['fixture_steps']}（{rep['fixture_exc']}） / "
      f"ReplayClient: 手数={rep['replay_steps']} 一致={rep['flags']}")

# --- 問題7 ------------------------------------------------------------------
top = symptom_top()
check("問題7 症状を頻度順に並べられる", top == ("同じ操作の反復", 2), f"1位={top[0]}（{top[1]} 件）")

# --- 問題8 ------------------------------------------------------------------
rows = sampling_summary()
check("問題8 テールベースのサンプリングを実装できる",
      [(r["kept"], r["kept_failures"], r["lost"]) for r in rows]
      == [("8/8", "5/5", 0), ("4/8", "2/5", 3), ("7/8", "5/5", 0)],
      " / ".join(f"{r['plan']}:{r['kept']}（取りこぼし {r['lost']}）" for r in rows))

# --- 問題9 ------------------------------------------------------------------
mr = masked_replay()
check("問題9 伏せ字にすると、伏せた区間から先が再生できない",
      (mr["無加工"]["steps"], mr["無加工"]["stop"]) == (3, "done")
      and (mr["伏せ字"]["steps"], mr["伏せ字"]["stop"]) == (1, "error"),
      f"無加工={mr['無加工']} / 伏せ字={mr['伏せ字']}")

# --- 問題10 -----------------------------------------------------------------
write_incident_report()
missing = incident_report_missing()
check("問題10 障害報告テンプレートが埋まる", missing == [],
      f"不足している見出し: {missing or 'なし'}（workspace/s14_incident.md）")

reset_data()
run_case("expense_report", "経費レポート作成")   # workspace/report.md を戻す

if failures:
    print(f"\n{len(failures)} 件の判定に失敗しました: {failures}")
    sys.exit(1)
print("\n練習問題の判定はすべて成功しました。")
