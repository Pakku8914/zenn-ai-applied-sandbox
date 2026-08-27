#!/usr/bin/env python3
"""セッション15：練習問題の参照解。

    python src/session15/ops_answers.py

**先に自分で書いてから読んでください。** 自分の実装で判定したい場合は、
この中の関数を自分のものに差し替える（または `verify_practice.py` の
インポート元を自分のファイルに変える）だけで動きます。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobspec import clear_workspace, reset_data, total_steps, workload  # noqa: E402
from queue_sim import (Scheduler, floor_seconds, knee, multiplicity_rows,  # noqa: E402
                       progress_at, run_crash, run_workload, strategy_rows)
from rollout import (POPULATION, canary_ids, check_runbook, kind_of,  # noqa: E402
                     measure, render_runbook)
from swap import accept_swap, swap_rows  # noqa: E402

RATE_LIMIT = 2


# --- 問題1：多重度の頭打ちを見つける ----------------------------------------
def knee_report() -> dict:
    """多重度を上げても速くならなくなる点と、その理由になる下限を返す。"""
    rows = multiplicity_rows()
    floor = floor_seconds(total_steps(workload()), RATE_LIMIT)
    return {"rows": rows, "floor": floor, "knee": knee(rows, floor)}


# --- 問題2：無駄になった呼び出しを数える ------------------------------------
def wasted_calls() -> dict:
    """2つの作法で「上限に当たって捨てた呼び出し」がいくつ出るか。"""
    return {row["label"]: row["wasted"] for row in strategy_rows()}


def strategy_summary() -> dict:
    """完了時刻と待機の合計。**待機が短い方が速いとは限らない**ことを示す。"""
    return {row["label"]: (row["makespan"], row["waited"]) for row in strategy_rows()}


# --- 問題3：進捗の見せ方 ------------------------------------------------------
def progress_report(job_id: str = "TASK-153", t: int = 4) -> dict:
    """％を出さない進捗。総ステップ数は走ってみるまで分からないため。"""
    return progress_at(run_workload(workers=2), job_id, t)


# --- 問題4：同期／非同期＋通知／バッチ の選択 --------------------------------
def choose_mode(expected_seconds: int, interactive: bool) -> str:
    """所要時間と「人が待っているか」で実行の形を選ぶ。"""
    if not interactive:
        return "バッチ"
    if expected_seconds <= 10:
        return "同期"
    return "非同期＋通知"


MODE_CASES = (
    ("規程を1つ引く", 3, True),
    ("経費レポートを作る", 120, True),
    ("全社員ぶんの月次レポートを夜間に作る", 3600, False),
    ("規程改定の影響を調べる", 600, True),
)


def mode_table() -> list[tuple[str, str]]:
    return [(label, choose_mode(sec, live)) for label, sec, live in MODE_CASES]


# --- 問題5：キャンセルで浮く呼び出し ----------------------------------------
def cancel_saving(job_id: str = "TASK-157", at: int = 9) -> tuple[int, int, int]:
    """(キャンセルなしの呼び出し, キャンセルありの呼び出し, 浮いた回数)。"""
    base = run_workload(workers=2)
    cut = run_workload(workers=2, cancel={job_id: at})
    return base.llm_calls, cut.llm_calls, base.llm_calls - cut.llm_calls


# --- 問題6：落ちたあとの方針を比べる ----------------------------------------
def crash_compare() -> dict:
    """チェックポイントから再開する／最初からやり直す の比較。"""
    out = {}
    for label, resume in (("再開する", True), ("やり直す", False)):
        r = run_crash(resume)
        out[label] = (r.makespan, r.llm_calls, r.redone_steps,
                      r.tool_counts["write_file"])
    return out


def resumed_matches_clean() -> bool:
    """再開した軌跡が、落ちなかった場合と一致するか（セッション6の結論）。"""
    from jobspec import crash_jobs  # noqa: PLC0415

    clean = Scheduler(crash_jobs(), workers=1).run().by_id("TASK-161").trajectory
    crashed = run_crash(True).by_id("TASK-161").trajectory
    return (clean.tool_names == crashed.tool_names
            and clean.final == crashed.final
            and len(clean.steps) == len(crashed.steps))


# --- 問題7：差し替えを出すかどうか ------------------------------------------
def swap_decisions() -> dict:
    """4つの新構成それぞれについて、本番に出すかを判断する。"""
    return {row["label"]: accept_swap(row) for row in swap_rows() if not row["base"]}


# --- 問題8：層化カナリア ------------------------------------------------------
def canary_detection(percent: int = 5) -> dict:
    """先頭から選ぶ／型ごとに選ぶ で、同じ割合でも検出できるかが変わる。"""
    out = {}
    for strategy in ("head", "stratified"):
        ids = canary_ids(percent, strategy)
        kinds = sorted({kind_of(tid) for tid in ids})
        out[strategy] = {"ids": ids, "kinds": kinds,
                         "forbidden": measure(ids, "new").forbidden}
    return out


def bucket_is_stable() -> bool:
    """同じ task_id は常に同じ群に入り、割合を上げると群は増えるだけ（単調）。"""
    for method in ("serial", "hash"):
        small = set(canary_ids(5, "head", method))
        large = set(canary_ids(25, "head", method))
        if not small <= large:
            return False
        if set(canary_ids(5, "head", method)) != small:
            return False
    return True


# --- 問題9：行列を公平にしないと何が起きるか --------------------------------
def fairness_rows() -> list[dict]:
    """到着順の行列を作る／作らない で、完了時刻と「最初の一歩までの待ち」を比べる。"""
    rows = []
    for label, fair in (("到着順に並べる（公平）", True), ("番号の若い順（不公平）", False)):
        r = run_workload(workers=4, fair=fair)
        rows.append({"label": label, "makespan": r.makespan, "waits": r.waits,
                     "max_wait_to_first_step": r.max_wait_to_first_step()})
    return rows


# --- 問題10：runbook ---------------------------------------------------------
def my_runbook() -> str:
    """自分で書いた runbook をここから返すようにする（既定は参照解）。"""
    return render_runbook()


def main() -> None:
    reset_data()          # 副作用（送信・ファイル作成）を出すので前後で戻す
    clear_workspace()
    print("=== 問題1 多重度の頭打ち ===")
    rep = knee_report()
    print(f"下限={rep['floor']} 秒 / 頭打ちの多重度={rep['knee']}")

    print("\n=== 問題2 無駄になった呼び出し ===")
    print(wasted_calls())
    print(strategy_summary())

    print("\n=== 問題3 進捗の見せ方 ===")
    print(progress_report())

    print("\n=== 問題4 実行の形の選択 ===")
    for label, mode in mode_table():
        print(f"{label} | {mode}")

    print("\n=== 問題5 キャンセルで浮く呼び出し ===")
    print("（なし, あり, 浮いた回数）=", cancel_saving())

    print("\n=== 問題6 落ちたあとの方針 ===")
    print("方針 | 完了 | 呼び出し | やり直し | write_file")
    for label, values in crash_compare().items():
        print(f"{label} | " + " | ".join(str(v) for v in values))
    print(f"再開した軌跡は落ちなかった場合と一致するか: {resumed_matches_clean()}")

    print("\n=== 問題7 差し替えの判断 ===")
    for label, verdict in swap_decisions().items():
        print(f"{label} | {verdict}")

    print("\n=== 問題8 カナリアの選び方 ===")
    for strategy, info in canary_detection().items():
        print(f"{strategy} | {len(info['ids'])} 件 | 型 {info['kinds']} | "
              f"禁止ツール {info['forbidden']} 件")
    print(f"振り分けは安定しているか: {bucket_is_stable()}")

    print("\n=== 問題9 行列の公平さ ===")
    print("方式 | 完了 | 待った回数 | 最初の一歩までの待ちの最大")
    for row in fairness_rows():
        print(f"{row['label']} | {row['makespan']} | {row['waits']} | "
              f"{row['max_wait_to_first_step']}")

    print("\n=== 問題10 runbook ===")
    ok, missing = check_runbook(my_runbook())
    print(f"節がそろっているか: {ok}（不足: {missing or 'なし'}）")
    print(f"母集団: {len(POPULATION)} 件")
    reset_data()
    clear_workspace()


if __name__ == "__main__":
    main()
