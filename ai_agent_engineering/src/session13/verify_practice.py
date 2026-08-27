#!/usr/bin/env python3
"""セッション13：練習問題の合否判定（参照解に対して実行する）。

    python src/session13/verify_practice.py

自分の実装に差し替えて走らせれば、そのまま自分の答えの判定になる。
1つでも落ちたら非0で終了する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ex_answers import (RUNBOOK_PATH, aggregate_variants, recommend_max_steps,  # noqa: E402
                        regression_matrix, score_runbook, silent_degrade_report,
                        stricter_injection_case, tolerance_compare, tool_f1,
                        write_runbook)
from evalspec import by_name, clear_artifact, reset_data, run_all, run_case  # noqa: E402
from judges import JUDGES, RUNS, execute, judge_all, judge_output  # noqa: E402
from scoreboard import summarize  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 問題1：6ケースの指標を再現する -----------------------------------------
reset_data()
pairs = run_all()
s = summarize(pairs)
check("問題1 6ケースの指標を再現できる",
      (round(s["success_rate"], 3), round(s["recall"], 3), round(s["mean_steps"], 2),
       s["declared_rate"]) == (0.667, 1.0, 3.83, 1.0),
      f"成功率={s['success_rate']:.3f} 再現率={s['recall']:.3f} "
      f"平均手数={s['mean_steps']:.2f} 期待整合率={s['declared_rate']:.3f}")

# --- 問題2：判定方式4種の表 --------------------------------------------------
table = {}
for run in RUNS:
    judged = judge_all(execute(run))
    table[run.label[0]] = "".join("○" if judged[name][0] else "×" for name in JUDGES)
check("問題2 判定方式4種の表が埋まる",
      (table["A"], table["B"], table["C"], table["D"])
      == ("○○○○", "○×○×", "○×××", "○○○×"),
      " ".join(f"{key}:{value}" for key, value in table.items()))

# --- 問題3：期待語を宣言する -------------------------------------------------
injection = by_name("injection_naive")
itraj = run_case(injection)
loose_ok, _ = judge_output(itraj, injection)
tight_ok, tight_why = judge_output(itraj, stricter_injection_case())
check("問題3 期待語を宣言すると出力判定が締まる", loose_ok and not tight_ok,
      f"期待語なし={'○' if loose_ok else '×'} / 期待語あり={'○' if tight_ok else '×'}"
      f"（{tight_why}）")

# --- 問題4：手数の分布から上限を決める ---------------------------------------
check("問題4 手数の分布から上限を決める", recommend_max_steps(pairs) == 6,
      f"推奨={recommend_max_steps(pairs)}（成功したケースの最大 "
      f"{max(len(t.steps) for c, t in pairs if c.expect_success)} + 余裕2・"
      f"現行の設定は8）")

# --- 問題5：適合率と F1 ------------------------------------------------------
f1s = [tool_f1(t, c.expected) for c, t in pairs]
check("問題5 適合率と F1 を出せる",
      round(s["precision"], 3) == 0.75 and round(sum(f1s) / len(f1s), 3) == 0.798,
      f"適合率={s['precision']:.3f} 平均F1={sum(f1s) / len(f1s):.3f}")

# --- 問題6：回帰の検出行列 ---------------------------------------------------
matrix = regression_matrix()
check("問題6 回帰の検出行列が作れる",
      len(matrix["write_file を外す"]) == 2 and len(matrix["get_policy を外す"]) == 1
      and matrix["send_message を外す"] == [] and matrix["なし（基準）"] == [],
      " / ".join(f"{label}:{len(detected)}方式" for label, detected in matrix.items()))

# --- 問題7：許容差の3案 ------------------------------------------------------
tol = tolerance_compare()
check("問題7 許容差の締め方で判定が変わる",
      (len(tol["締めた案"]), len(tol["本文の案"]), len(tol["緩めた案"])) == (1, 3, 3),
      " / ".join(f"{label}={len(same)}本" for label, same in tol.items()))

# --- 問題8：静かな劣化 -------------------------------------------------------
degrade = silent_degrade_report()
check("問題8 4方式を通り抜ける劣化を内容検査で捕まえる",
      all(degrade["verdicts"].values()) and degrade["same_final"]
      and degrade["missing_degraded"] == ["規程違反", "EXP-0002"],
      f"4方式すべて○・最終回答も同一 / 成果物の不足={degrade['missing_degraded']}")

# --- 問題9：複数回実行の集計 -------------------------------------------------
agg = aggregate_variants()
check("問題9 複数回実行を分布で集計できる",
      (agg["n"], agg["success"], agg["same_result"], agg["hard_total"]) == (5, 3, 3, 5),
      f"n={agg['n']} 成功={agg['success']} 同じ結果={agg['same_result']} "
      f"許容しない差={agg['hard_total']}")

# --- 問題10：評価 runbook の採点 ---------------------------------------------
write_runbook()
score = score_runbook(RUNBOOK_PATH.read_text(encoding="utf-8"))
check("問題10 評価 runbook が4観点を満たす", score["passed"] == score["total"],
      f"{score['passed']}/{score['total']}（落ちた検査: "
      f"{'／'.join(score['missing']) or 'なし'}）")

# --- 後片付け ---------------------------------------------------------------
reset_data()
report = by_name("expense_report")
clear_artifact(report)
run_case(report)

if failures:
    print(f"\n{len(failures)} 件の判定に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション13の練習問題の判定はすべて成功しました。")
