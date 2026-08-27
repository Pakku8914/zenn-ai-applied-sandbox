#!/usr/bin/env python3
"""復習04：上限に当たったとき、利用者に何を返すか（問題9）。

    python src/review04/stopping.py

コスト上限も手数の上限も、置いただけでは設計になっていない。**上限に達したあとに
利用者が何を受け取るか**まで決めて初めて設計である。

ここで混ぜてはいけないものが3つある。

  停止理由（`stop_reason`）… なぜループが止まったか（done / max_steps / budget / error）
  ジョブの状態（`state`） … キューから見た結末（done / limited / cancelled / failed）
  結果（outcome）         … 依頼した人が受け取ったもの（report / partial / insufficient / handoff）

3つは**別の軸**である（Mid01 で決めたとおり）。「引き継ぎます」と書いた文面が出ることと、
結果が handoff であることも別で、打ち切りは材料が足りないので insufficient になる。
"""

from __future__ import annotations

from _paths import reset_data, setup

ROOT = setup()

from jobspec import artifact_text, clear_workspace  # noqa: E402
from queue_sim import run_isolation, run_workload  # noqa: E402

OUTCOMES = ("report", "partial", "insufficient", "handoff")


def outcome_for(state: str, stop_reason: str, side_effect: bool,
                partial_artifact: bool) -> str:
    """結果を1つ返す。**見る順に意味がある。**

    ① 完走したなら report
    ② 人が止めたなら handoff（途中経過は人が読む前提で渡す）
    ③ 例外で落ちたなら handoff（何が実行されたか分からないので人に渡すしかない）
    ④ 副作用か部分成果が残っているなら partial（「何も起きていない」と言えない）
    ⑤ どれでもなければ insufficient（材料が足りずに終わった）
    """
    if stop_reason == "done":
        return "report"
    if state == "cancelled":
        return "handoff"
    if stop_reason == "error":
        return "handoff"
    if side_effect or partial_artifact:
        return "partial"
    return "insufficient"


# 宣言した6ケース（状態, stop_reason, 副作用, 部分成果, 期待する結果）
CASES: tuple[tuple[str, str, bool, bool, str], ...] = (
    ("done", "done", False, True, "report"),
    ("limited", "max_steps", True, True, "partial"),
    ("limited", "max_steps", False, False, "insufficient"),
    ("limited", "budget", True, False, "partial"),
    ("cancelled", "error", False, False, "handoff"),
    ("failed", "error", True, False, "handoff"),
)


def case_rows() -> list[dict]:
    return [{"状態": state, "stop_reason": stop, "副作用": "あり" if eff else "なし",
             "部分成果": "あり" if art else "なし",
             "結果": outcome_for(state, stop, eff, art), "期待": want}
            for state, stop, eff, art, want in CASES]


def handoff_note(final: str | None) -> str:
    """引き継ぎ書が出ているか（文面の有無。結果の分類とは別）。"""
    text = final or ""
    if "利用者がキャンセルしました" in text:
        return "あり（利用者がキャンセルしました）"
    if "人に引き継ぎます" in text:
        return "あり（人に引き継ぎます）"
    return "—"


def live_rows() -> list[dict]:
    """S15 のスケジューラを実際に走らせて3件を取る。

    このワークロードは `data/*.jsonl` を変えない（書くのは作業領域のファイルだけ）。
    そこで副作用は False とし、書けたファイルを「部分成果」として数える。
    """
    reset_data()
    clear_workspace()

    iso = run_isolation()
    runaway = iso.by_id("TASK-172")
    cut = run_workload(workers=2, cancel={"TASK-157": 9})
    finished = cut.by_id("TASK-153")
    stopped = cut.by_id("TASK-157")

    rows = []
    for run in (finished, runaway, stopped):
        traj = run.trajectory
        partial = bool(artifact_text(run.job.job_id))
        rows.append({
            "job_id": run.job.job_id, "状態": run.state,
            "stop_reason": traj.stop_reason, "手数": run.steps_done,
            "成果物": "あり" if partial else "なし",
            "結果": outcome_for(run.state, traj.stop_reason, False, partial),
            "引き継ぎ書": handoff_note(traj.final),
        })

    reset_data()
    clear_workspace()
    return rows


def main() -> None:
    print("=== 上限に当たったとき、利用者に何を返すか（宣言した6ケース）===")
    print("# | 状態 | stop_reason | 副作用 | 部分成果 | 結果(outcome)")
    for i, row in enumerate(case_rows(), start=1):
        print(f"{i} | {row['状態']} | {row['stop_reason']} | {row['副作用']} | "
              f"{row['部分成果']} | {row['結果']}")

    print("\n=== 実際に走らせた3件（S15 のスケジューラ）===")
    print("job_id | 状態 | stop_reason | 手数 | 成果物 | 結果 | 引き継ぎ書")
    for row in live_rows():
        print(" | ".join([row["job_id"], row["状態"], row["stop_reason"],
                          str(row["手数"]), row["成果物"], row["結果"],
                          row["引き継ぎ書"]]))

    print("\n=== 読み取れること ===")
    print("- 打ち切り（max_steps）の結果は insufficient であって handoff ではない。"
          "文面に「人に引き継ぎます」と書いてあっても、受け取ったものは材料不足である。")
    print("- 例外で落ちた場合だけは、副作用があっても partial にしない。"
          "何が実行されたか分からないものを「一部できました」と返してはいけない。")
    print("- 停止理由・ジョブの状態・結果は別の軸である。3つとも記録する。")


if __name__ == "__main__":
    main()
