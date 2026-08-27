#!/usr/bin/env python3
"""エージェント版の会議室予約：制御を LLM 側に渡す。

同じ業務要求・同じツールでも、「次に何をするか」を決めるのがモデルになると
挙動が変わる。ここでは3つの軌跡を用意する。

  1. 競合してから別の時間帯に切り替える（既存シナリオ book_room_conflict）
  2. 経路が事前に決まらない要求に、実行時の判断で到達する（CAPACITY_SCENARIO）
  3. 誤ったツールを選び、やっていないことを「完了しました」と報告する（WRONG_TOOL_SCENARIO）

シナリオはこのファイルの中に持つ（scenarios/ の既存ファイルは変更しない）。
`ScriptedClient` は辞書をそのまま受け取れる。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402

# tools/traj_stats.py と同じ条件（シナリオ・タスク文・上限）で走らせる。
# 実測値の表と数値を突き合わせられるようにするため、タスク文まで揃えている。
CONFLICT_TASK = "会議室予約（競合あり）"

CAPACITY_TASK = "13:00 から1時間、10名が入る会議室を確保してください"

# 経路が事前に決まらない要求。大会議室（定員40）の 13:00 が埋まっているため、
# 「定員10名以上の別室」を実行時に選び直す必要がある。
CAPACITY_SCENARIO = {
    "name": "s02_capacity",
    "description": "規程を読み、優先すべき部屋が埋まっていたので条件を満たす別室に切り替える",
    "turns": [
        {
            "thought": "会議室予約の規程を確認する。",
            "calls": [{"name": "get_policy", "args": {"topic": "会議室予約"}}],
        },
        {
            "thought": "10名以上は大会議室を優先すると書かれているので、まず大会議室を押さえる。",
            "calls": [{"name": "book_room",
                       "args": {"room": "大会議室", "start": "13:00", "minutes": 60}}],
        },
        {
            "thought": "競合していた。定員10名以上を満たす別室（みなと・定員12名）に切り替える。",
            "calls": [{"name": "book_room",
                       "args": {"room": "みなと", "start": "13:00", "minutes": 60}}],
        },
        {
            "thought": "確保できたので報告する。",
            "final": "みなと会議室（定員12名）を13:00から60分で確保しました。"
                     "大会議室は13:00が埋まっていたため変更しています。",
        },
    ],
}

# 同じ要求に対して、道具の選択を誤ったまま「完了しました」と報告してしまう軌跡。
# 失敗モードの観測（failure_modes.py）で使う。
WRONG_TOOL_SCENARIO = {
    "name": "s02_wrong_tool",
    "description": "予約ツールを使わず、検索と送信で済ませたつもりになって嘘の報告をする",
    "turns": [
        {
            "thought": "会議室の予約方法を文書で調べる。",
            "calls": [{"name": "search_docs",
                       "args": {"query": "会議室予約", "limit": 1}}],
        },
        {
            "thought": "総務に依頼すればよいはずなので、メッセージを送る。",
            "calls": [{"name": "send_message",
                       "args": {"to": "external@example.com",
                                "body": "13:00 の会議室を押さえてください。"}}],
        },
        {
            "thought": "依頼したので完了とする。",
            "final": "13:00 の会議室を確保しました（予約番号 BK-0007）。",
        },
    ],
}


def run(scenario: str | dict, task: str, *, task_id: str = "TASK-002",
        max_steps: int = 8) -> Trajectory:
    """シナリオを1本走らせて軌跡を返す。"""
    agent = ReActAgent(ScriptedClient(scenario), build_registry(), max_steps=max_steps)
    return agent.run(task, task_id=task_id)


def run_conflict_retry() -> Trajectory:
    """10:00 が競合し、11:00 に切り替えて完了する軌跡。"""
    return run("book_room_conflict", CONFLICT_TASK, task_id="TASK-book_room_conflict")


def run_capacity() -> Trajectory:
    """経路が事前に決まらない要求に、実行時の判断で到達する軌跡。"""
    return run(CAPACITY_SCENARIO, CAPACITY_TASK, task_id="TASK-s02-capacity")


def run_wrong_tool() -> Trajectory:
    """道具を誤り、やっていないことを報告する軌跡。"""
    return run(WRONG_TOOL_SCENARIO, CAPACITY_TASK, task_id="TASK-s02-wrong-tool")


def show(label: str, traj: Trajectory) -> None:
    """軌跡を1件表示する。失敗したツール結果だけ本文を出す。"""
    print(f"--- {label} ---")
    print(f"停止理由: {traj.stop_reason} / 手数: {len(traj.steps)} / "
          f"LLM 呼び出し: {len(traj.steps)} 回 / ツール呼び出し: {len(traj.tool_names)} 回")
    for step in traj.steps:
        names = ", ".join(c.name for c in step.calls) or "（最終回答）"
        print(f"  step {step.index}: {names}")
        for result in step.results:
            if not result.ok:
                print(f"      NG {result.error}")
    print(f"最終回答: {traj.final}")


def main() -> None:
    print("=== 競合してから別の時間帯に切り替える ===")
    show("book_room_conflict", run_conflict_retry())

    print("\n=== 経路が固定できない要求（13:00 に定員10名以上）===")
    show("s02_capacity", run_capacity())

    print("\n=== 道具を誤り、やっていないことを報告する ===")
    show("s02_wrong_tool", run_wrong_tool())
    print("※ book_room を1度も呼んでいないのに『確保しました』と報告している。")


if __name__ == "__main__":
    main()
