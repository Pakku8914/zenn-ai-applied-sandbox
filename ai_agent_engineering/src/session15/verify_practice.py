#!/usr/bin/env python3
"""セッション15の練習問題の判定。

    python src/session15/verify_practice.py

参照解（`ops_answers.py`）に対して判定する。自分の実装で判定したい場合は、
`ops_answers.py` の関数を差し替えるか、このファイルのインポート元を変える。
副作用を出すので、冒頭と末尾でデータと作業領域を初期状態に戻す。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobspec import clear_workspace, reset_data  # noqa: E402
from ops_answers import (bucket_is_stable, canary_detection, cancel_saving,  # noqa: E402
                         crash_compare, fairness_rows, knee_report, mode_table,
                         my_runbook, progress_report, resumed_matches_clean,
                         strategy_summary, swap_decisions, wasted_calls)
from rollout import check_runbook  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


reset_data()
clear_workspace()

# --- 問題1 -------------------------------------------------------------------
rep = knee_report()
check("問題1 多重度の頭打ちと下限を説明できる",
      rep["floor"] == 12 and rep["knee"] == 2,
      f"下限 {rep['floor']} 秒 / 頭打ち 多重度 {rep['knee']}")

# --- 問題2 -------------------------------------------------------------------
wasted = wasted_calls()
summary = strategy_summary()
check("問題2 無駄になった呼び出しを数えられる",
      set(wasted.values()) == {6, 0}
      and wasted["当たってから謝る（バックオフ）"] == 6,
      f"{wasted}")
check("問題2 待機の合計と完了時刻が逆転していることを示せる",
      summary["当たってから謝る（バックオフ）"] == (7, 8)
      and summary["手前で順番待ち（行列）"] == (6, 10),
      f"{summary}")

# --- 問題3 -------------------------------------------------------------------
view = progress_report()
check("問題3 ％を使わない進捗を返せる",
      view == {"job_id": "TASK-153", "state": "running", "steps_done": 3,
               "last_action": "write_file", "waited_seconds": 0, "started_at": 2},
      str(view))

# --- 問題4 -------------------------------------------------------------------
check("問題4 実行の形を選び分けられる",
      [mode for _label, mode in mode_table()]
      == ["同期", "非同期＋通知", "バッチ", "非同期＋通知"],
      " / ".join(f"{label}→{mode}" for label, mode in mode_table()))

# --- 問題5 -------------------------------------------------------------------
check("問題5 キャンセルで浮く呼び出しを数えられる", cancel_saving() == (24, 21, 3),
      f"（なし, あり, 浮いた）= {cancel_saving()}")

# --- 問題6 -------------------------------------------------------------------
crash = crash_compare()
check("問題6 落ちたあとの方針で結果が変わることを示せる",
      crash == {"再開する": (6, 6, 0, 1), "やり直す": (9, 9, 3, 2)}, str(crash))
check("問題6 再開した軌跡が落ちなかった場合と一致する", resumed_matches_clean(),
      "ツール列・最終回答・手数が一致")

# --- 問題7 -------------------------------------------------------------------
decisions = swap_decisions()
check("問題7 差し替えの受け入れ基準を書ける",
      decisions == {"A 同じ挙動": "出す", "B 余計に調べる": "様子を見る",
                    "C 禁止ツールを呼ぶ": "出さない", "D 中身が薄くなる": "出さない"},
      str(decisions))

# --- 問題8 -------------------------------------------------------------------
detect = canary_detection()
check("問題8 層化カナリアなら 5% で欠陥に当たる",
      detect["head"]["forbidden"] == 0 and detect["stratified"]["forbidden"] == 1
      and "send" in detect["stratified"]["kinds"]
      and "send" not in detect["head"]["kinds"],
      f"先頭から={detect['head']['kinds']} / 型ごと={detect['stratified']['kinds']}")
check("問題8 振り分けは安定していて単調に広がる", bucket_is_stable(),
      "同じ task_id は常に同じ群 / 5% の集合 ⊂ 25% の集合")

# --- 問題9 -------------------------------------------------------------------
rows = {r["label"]: r for r in fairness_rows()}
fair = rows["到着順に並べる（公平）"]
unfair = rows["番号の若い順（不公平）"]
check("問題9 行列の公平さのトレードオフを数字で出せる",
      (fair["makespan"], fair["waits"], fair["max_wait_to_first_step"]) == (13, 19, 1)
      and (unfair["makespan"], unfair["waits"],
           unfair["max_wait_to_first_step"]) == (12, 17, 9),
      f"公平 {fair['makespan']}秒/最大待ち{fair['max_wait_to_first_step']}秒 ／ "
      f"不公平 {unfair['makespan']}秒/最大待ち{unfair['max_wait_to_first_step']}秒")

# --- 問題10 ------------------------------------------------------------------
ok, missing = check_runbook(my_runbook())
check("問題10 runbook に必要な節がそろっている", ok, f"不足: {missing or 'なし'}")

reset_data()
clear_workspace()

if failures:
    print(f"\n{len(failures)} 件の判定に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション15の練習問題の判定はすべて成功しました。")
