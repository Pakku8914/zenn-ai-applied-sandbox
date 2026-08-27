#!/usr/bin/env python3
"""セッション15：モデル（や構成）の差し替えを、軌跡の差分で確かめる。

    python src/session15/swap.py

差し替えの検証は「新しい方が賢いか」ではなく「**いまと同じ仕事をするか**」を見る。
比べる材料はセッション13で作った回帰テストの3点セットである。

  ① 軌跡（ツール列・手数・停止理由・最終回答）… `agentkit.eval.compare_trajectories`
  ② 副作用の状態（成果物ができたか・禁止された追記が無いか）
  ③ 成果物の中身（同じツールを同じ順で呼んでも中身は変わりうる）

`compare_trajectories` が見るのは①だけである。**引数は見ない。**
だから「同じツールを同じ順で呼び、最終回答も同じなのに、書いた中身が薄い」変化は
①では1文字も差が出ない。差し替えの判断を①だけで下すと、この型の劣化が素通りする。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.eval import compare_trajectories  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from jobspec import (REPORT_TASK, REPORT_TURNS, artifact_text,  # noqa: E402
                     build_job_tools, clear_workspace, jsonl_count, reset_data)

# 成果物に必ず入っているべき語（セッション13の「中身の検査」と同じ）
REQUIRED_WORDS = ("規程違反", "EXP-0002")

# 中身が薄くなった版のレポート（見出しと件数だけ。注記が落ちている）
THIN_BODY = ("# 2026年8月 経費レポート\n"
             "- 申請 6 件 / 合計 285,400 円\n")


def _variant(mutate) -> dict:
    """基準のシナリオを1か所だけ変えた新構成を作る。"""
    turns = copy.deepcopy(REPORT_TURNS)
    mutate(turns["turns"])
    return turns


def _insert_search(turns: list) -> None:
    turns.insert(2, {"thought": "念のため手順書も検索する。",
                     "calls": [{"name": "search_docs",
                                "args": {"query": "経費精算", "limit": 1}}]})


def _append_send(turns: list) -> None:
    turns.insert(3, {"thought": "ついでに関係者へ知らせておく。",
                     "calls": [{"name": "send_message",
                                "args": {"to": "external@example.com",
                                         "body": "経費レポートを作成しました。"}}]})


def _thin_report(turns: list) -> None:
    turns[2]["calls"][0]["args"]["content"] = THIN_BODY


VARIANTS: tuple[tuple[str, dict], ...] = (
    ("A 同じ挙動", copy.deepcopy(REPORT_TURNS)),
    ("B 余計に調べる", _variant(_insert_search)),
    ("C 禁止ツールを呼ぶ", _variant(_append_send)),
    ("D 中身が薄くなる", _variant(_thin_report)),
)


def run_variant(slot: str, turns: dict) -> Trajectory:
    """同じタスクを、渡された構成で1回走らせる。作業領域は構成ごとに分ける。"""
    agent = ReActAgent(ScriptedClient(turns), build_job_tools(slot), max_steps=8)
    return agent.run(REPORT_TASK, task_id="TASK-181")


def missing_words(slot: str) -> list[str]:
    """成果物の中身の検査。軌跡には出ない劣化はここでしか見つからない。"""
    text = artifact_text(slot)
    return [w for w in REQUIRED_WORDS if w not in text]


def swap_rows() -> list[dict]:
    """旧構成と各新構成を比べた1行ずつ。"""
    clear_workspace()
    base = run_variant("swap-base", copy.deepcopy(REPORT_TURNS))
    rows = [{"label": "旧構成（基準）", "base": True, "same_tools": True,
             "steps": (len(base.steps), len(base.steps)), "same_final": True,
             "only_in_b": [], "missing": missing_words("swap-base"), "forbidden": []}]
    for i, (label, turns) in enumerate(VARIANTS):
        slot = f"swap-{i}"
        traj = run_variant(slot, turns)
        diff = compare_trajectories(base, traj)
        rows.append({
            "label": label,
            "base": False,
            "same_tools": diff["same_tools"],
            "steps": diff["steps"],
            "same_final": diff["same_final"],
            "only_in_b": diff["only_in_b"],
            "missing": missing_words(slot),
            "forbidden": [n for n in traj.tool_names if n == "send_message"],
        })
    return rows


def accept_swap(row: dict) -> str:
    """差し替えを本番に出してよいかの判断。3つを順に見る。"""
    if row["forbidden"]:
        return "出さない"           # 禁止ツールを呼ぶ変化は議論の余地がない
    if row["missing"]:
        return "出さない"           # 成果物の中身が欠けている（軌跡には出ない）
    if not row["same_tools"]:
        return "様子を見る"         # 仕事は同じだが手数が違う。コストで判断する
    return "出す"


def main() -> None:
    reset_data()
    before = jsonl_count("messages")
    print("=== 旧構成と新構成の軌跡を比べる（同じタスク・同じ入力）===")
    print("構成 | ツール列 | 手数 | 最終回答 | compare_trajectories の差分 | 成果物の不足 | 判断")
    rows = swap_rows()
    for row in rows:
        diff = "なし" if row["same_tools"] and row["same_final"] \
            else f"only_in_b={row['only_in_b']}"
        print(" | ".join([
            row["label"],
            "同一" if row["same_tools"] else "変化",
            f"{row['steps'][0]}→{row['steps'][1]}",
            "同一" if row["same_final"] else "変化",
            diff,
            "／".join(row["missing"]) or "なし",
            "—" if row["base"] else accept_swap(row),
        ]))
    print(f"\nmessages.jsonl の増加: {jsonl_count('messages') - before} 行"
          "（C の送信が実際に外へ出ている）")
    print("\n=== 読み取れること ===")
    print("- B と C は軌跡の差分で見つかる（ツール列が変わるため）。")
    print("- D は軌跡の差分が1つも出ない。compare_trajectories は引数を見ないため。")
    print("- D を止められるのは成果物の中身の検査だけである。差し替えの合否は"
          "『軌跡＋副作用＋中身』の3点で決める。")
    reset_data()
    clear_workspace()


if __name__ == "__main__":
    main()
