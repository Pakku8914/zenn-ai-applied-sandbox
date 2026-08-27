#!/usr/bin/env python3
"""セッション13：回帰テスト — ツール定義を1つ変えて、影響を検出する。

    python src/session13/regress.py

回帰テストは「同じ入力で同じ結果になること」を固定する仕掛けである。本章の環境は
モデルが決定的なので、変えたのはこちら側だけ（ツール定義）だと言い切れる。

ここで示すのは、**軌跡が1文字も変わらない回帰**が実在することである。
だから回帰テストは3点セットで書く。

  ① 軌跡（ツール列・手数・停止理由）
  ② 副作用の状態（成果物ができたか・禁止された追記が無いか）
  ③ 失敗したツール結果が残っていないこと
"""

from __future__ import annotations

from pathlib import Path

from evalspec import (ROOT, Case, added_since, artifact_ok, by_name,  # noqa: E402
                      clear_artifact, counts, reset_data, run_case)
from judges import (JUDGES, failed_calls, judge_output, judge_state,  # noqa: E402
                    judge_strict, judge_trajectory)

from agentkit.models import Trajectory  # noqa: E402

# ツール定義の変更（回帰の題材）。「外す」は最も分かりやすい変更のひとつ
CHANGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("なし（基準）", ()),
    ("write_file を外す", ("write_file",)),
    ("get_policy を外す", ("get_policy",)),
    ("send_message を外す", ("send_message",)),
)


def baseline_path(case: Case) -> Path:
    """軌跡ファイルの命名規約は `traces/{task_id}_{scenario}.jsonl`。"""
    return ROOT / "traces" / f"TASK-{case.name}_baseline.jsonl"


def save_baseline(case: Case) -> Trajectory:
    clear_artifact(case)
    traj = run_case(case)
    traj.to_jsonl(baseline_path(case))
    return traj


def load_baseline(case: Case) -> Trajectory:
    """JSONL から読み戻す。基準は**ファイル**に置く（実行のたびに作り直さない）。"""
    return Trajectory.from_jsonl(baseline_path(case))


def observe(case: Case, drop: tuple[str, ...]) -> dict:
    """1回の走行から、判定に必要な観測をすべて集める。"""
    reset_data()
    clear_artifact(case)
    before = counts()
    traj = run_case(case, drop)
    return {"traj": traj, "added": added_since(before), "artifact": artifact_ok(case),
            "failed": failed_calls(traj)}


def detected_by(case: Case, obs: dict) -> list[str]:
    """4つの判定方式のうち、この変更を検出できたものを返す。"""
    verdicts = {
        "出力の内容": judge_output(obs["traj"], case),
        "副作用の状態": judge_state(case, obs["added"], obs["artifact"]),
        "軌跡の一致": judge_trajectory(obs["traj"], case),
        "軌跡の一致（厳格）": judge_strict(obs["traj"], case),
    }
    return [name for name in JUDGES if not verdicts[name][0]]


def main() -> None:
    case = by_name("expense_report")

    print("=== 基準の軌跡を保存する ===")
    base = save_baseline(case)
    print(f"{baseline_path(case).relative_to(ROOT)} に {len(base.steps)} ステップを"
          "保存しました。")
    restored = load_baseline(case)
    print(f"読み戻した軌跡: 手数={len(restored.steps)} 停止理由={restored.stop_reason} "
          f"ツール={restored.tool_names} 最終回答の一致={restored.final == base.final}")

    print("\n=== ツール定義を1つ変えて再実行する ===")
    print("変更 | ツール列 | 手数 | 停止理由 | 最終回答 | 成果物 | 失敗した結果 | 検出した判定")
    for label, drop in CHANGES:
        obs = observe(case, drop)
        traj = obs["traj"]
        print(" | ".join([
            label,
            "同一" if traj.tool_names == restored.tool_names else "変化",
            str(len(traj.steps)),
            traj.stop_reason,
            "同一" if traj.final == restored.final else "変化",
            "あり" if obs["artifact"] else "なし",
            str(len(obs["failed"])),
            "／".join(detected_by(case, obs)) or "—",
        ]))

    print("\n=== 読み取れること ===")
    print("- ツール定義を1つ外しても、ツール列・手数・停止理由・最終回答は1文字も変わらない。")
    print("- write_file を外した回帰は「成果物ができていない」でしか見つからない。")
    print("- get_policy を外した回帰は「失敗した結果が残っている」でしか見つからない。")
    print("- 期待に無いツール（send_message）を外しても何も変わらない＝影響範囲が分かる。")

    # 後片付け：成果物を作り直し、データを初期状態に戻す
    save_baseline(case)
    reset_data()
    print("\n後片付け: 基準の軌跡と workspace/report.md を作り直し、data/ を初期化しました。")


if __name__ == "__main__":
    main()
