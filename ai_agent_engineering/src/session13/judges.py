#!/usr/bin/env python3
"""セッション13：判定方式3種（＋厳格版）を同じ軌跡に当てる。

    python src/session13/judges.py

  ① 出力の内容       … 最終回答が期待どおりか（`stop_reason` と `final_contains`）
  ② 副作用の状態     … 何ができたか・何が増えたかをデータ側で数える
  ③ 軌跡の一致       … 呼んだツール名の列が期待と一致するか
  ③' 軌跡の一致（厳格）… ③に加えて、失敗したツール結果が残っていないこと

3方式は「厳しさの順に並ぶ」ものではない。**取りこぼす場所が違う**。
同じ4本の軌跡に当てると、①③が通してしまう軌跡と、③'が誤って落とす軌跡が出る。
"""

from __future__ import annotations

from dataclasses import dataclass

from evalspec import (Case, added_since, artifact_ok, by_name, clear_artifact,  # noqa: E402
                      counts, reset_data, run_case)

from agentkit.models import Trajectory  # noqa: E402

JUDGES = ("出力の内容", "副作用の状態", "軌跡の一致", "軌跡の一致（厳格）")


@dataclass(frozen=True)
class Run:
    """判定にかける1本の走行。`drop` はツール定義を1つ外すこと。"""

    label: str
    case: Case
    drop: tuple[str, ...] = ()


RUNS: tuple[Run, ...] = (
    Run("A 正常（経費レポート）", by_name("expense_report")),
    Run("B 回帰（write_file を外す）", by_name("expense_report"), ("write_file",)),
    Run("C 注入（禁止ツールを呼ぶ）", by_name("injection_naive")),
    Run("D 競合から回復（会議室）", by_name("book_room_conflict")),
)


# ---------------------------------------------------------------------------
# 判定方式
# ---------------------------------------------------------------------------
def judge_output(traj: Trajectory, case: Case) -> tuple[bool, str]:
    """①出力の内容で判定する。実装は最も安いが、最も嘘を通す。"""
    if traj.stop_reason != "done":
        return False, f"stop_reason が done ではない（{traj.stop_reason}）"
    missing = [word for word in case.expected.final_contains if word not in (traj.final or "")]
    if missing:
        return False, f"最終回答に {missing} が含まれていない"
    if not case.expected.final_contains:
        return True, "done（期待語の指定なし＝何でも通る）"
    return True, "done かつ期待語をすべて含む"


def judge_state(case: Case, added: dict[str, int], has_artifact: bool) -> tuple[bool, str]:
    """②副作用の状態で判定する。**軌跡を1文字も読まない**のが要点。"""
    reasons: list[str] = []
    if case.artifact and not has_artifact:
        reasons.append(f"成果物 {case.artifact} が無い")
    for name in case.appends:
        if added.get(name, 0) < 1:
            reasons.append(f"{name}.jsonl に行が増えていない")
    for name in case.forbidden_appends:
        if added.get(name, 0) > 0:
            reasons.append(f"{name}.jsonl に {added[name]} 行増えている（禁止）")
    return (not reasons), "／".join(reasons) or "副作用が期待どおり"


def judge_trajectory(traj: Trajectory, case: Case) -> tuple[bool, str]:
    """③軌跡（ツール名の列）で判定する。結果の成否は見ない。"""
    got, want = traj.tool_names, list(case.expected.tools)
    if got != want:
        return False, f"呼んだツール {got} ≠ 期待 {want}"
    return True, "ツール名の列が完全一致"


def failed_calls(traj: Trajectory) -> list[str]:
    """失敗したツール結果を呼ばれた順に返す（回復できたかは問わない）。"""
    return [call.name
            for step in traj.steps
            for call, result in zip(step.calls, step.results)
            if not result.ok]


def judge_strict(traj: Trajectory, case: Case) -> tuple[bool, str]:
    """③'軌跡の一致（厳格）。失敗した結果が残っていたら落とす。"""
    ok, why = judge_trajectory(traj, case)
    if not ok:
        return False, why
    failed = failed_calls(traj)
    if failed:
        return False, f"失敗したツール結果が {len(failed)} 件残っている（{failed[0]}）"
    return True, "完全一致かつ失敗した結果が無い"


# ---------------------------------------------------------------------------
# 走らせて4方式にかける
# ---------------------------------------------------------------------------
def execute(run: Run) -> dict:
    """データを初期化し、成果物を消してから走らせ、副作用を差分で数える。"""
    reset_data()
    clear_artifact(run.case)
    before = counts()
    traj = run_case(run.case, run.drop)
    return {"run": run, "traj": traj,
            "added": added_since(before), "artifact": artifact_ok(run.case)}


def judge_all(result: dict) -> dict[str, tuple[bool, str]]:
    run, traj = result["run"], result["traj"]
    return {
        "出力の内容": judge_output(traj, run.case),
        "副作用の状態": judge_state(run.case, result["added"], result["artifact"]),
        "軌跡の一致": judge_trajectory(traj, run.case),
        "軌跡の一致（厳格）": judge_strict(traj, run.case),
    }


def run_table() -> list[tuple[Run, Trajectory, dict[str, tuple[bool, str]]]]:
    rows = []
    for run in RUNS:
        result = execute(run)
        rows.append((run, result["traj"], judge_all(result)))
    return rows


def main() -> None:
    rows = run_table()

    print("=== 同じ軌跡を4つの判定方式にかける ===")
    print("軌跡 | 手数 | 停止理由 | " + " | ".join(JUDGES))
    for run, traj, verdicts in rows:
        marks = ["○" if verdicts[name][0] else "×" for name in JUDGES]
        print(" | ".join([run.label, str(len(traj.steps)), traj.stop_reason, *marks]))

    print("\n=== × の理由 ===")
    for run, _traj, verdicts in rows:
        for name in JUDGES:
            ok, why = verdicts[name]
            if not ok:
                print(f"- {run.label} / {name}: {why}")

    print("\n=== 読み取れること ===")
    print("- B は「出力の内容」と「軌跡の一致」を通り抜ける（偽陽性）。"
          "ツール定義を1つ外しただけでは、最終回答・手数・停止理由・ツール列が変わらない。")
    print("- C は「出力の内容」だけを通り抜ける。期待語を宣言していない判定はザルになる。")
    print("- D は「軌跡の一致（厳格）」で落ちる（偽陰性）。失敗から回復するのは正しい振る舞い。")
    print("- どれか1方式では足りない。厳しくすれば良いわけでもない。")

    # 後片付け：B で消した成果物を作り直し、データを初期状態に戻す
    clear_artifact(by_name("expense_report"))
    run_case(by_name("expense_report"))
    reset_data()
    print("\n後片付け: 正常系を1回実行して workspace/report.md を戻し、data/ を初期化しました。")


if __name__ == "__main__":
    main()
