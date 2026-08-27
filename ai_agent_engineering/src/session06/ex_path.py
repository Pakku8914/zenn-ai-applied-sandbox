#!/usr/bin/env python3
"""軌跡から「実際に通った経路」を図にする（セッション6の発展課題の解答）。

状態遷移図は「起こりうること」を描いた設計図で、軌跡は「実際に起きたこと」の記録である。
両方を並べると、テストがどこを通していないかが見える（セッション13の伏線）。

    python src/session06/ex_path.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import Trajectory  # noqa: E402
from states import TRANSITIONS  # noqa: E402


def visited_edges(traj: Trajectory) -> list[str]:
    """軌跡が通った遷移を、出てきた順に重複なく並べる。

    遷移先は「次のステップに記録されている状態」から復元する。
    状態機械のインスタンスは再開のたびに作り直されるが、
    各ステップの `usage` に state と event を書いてあるので軌跡だけで復元できる。

    最後のステップにイベントが入っている場合、その遷移先は軌跡から分からないので
    `?` になる。これは「ステップ境界の外で終わった」（打ち切り・致命的停止）印であり、
    そのときの最終状態はチェックポイントの `state` 側で確認する。
    """
    edges: list[str] = []
    for index, step in enumerate(traj.steps):
        event = step.usage.get("event") or ""
        if not event:
            continue
        src = step.usage.get("state", "?")
        dst = (traj.steps[index + 1].usage.get("state", "?")
               if index + 1 < len(traj.steps) else "?")
        edge = f"{src} --> {dst}: {event}"
        if edge not in edges:
            edges.append(edge)
    return edges


def traj_to_mermaid(traj: Trajectory) -> str:
    """実際に通った経路だけの状態遷移図を出す。"""
    return "\n".join(["stateDiagram-v2", *[f"    {e}" for e in visited_edges(traj)]])


def all_edges() -> list[str]:
    """定義されている遷移をすべて並べる。"""
    return [f"{src} --> {dst}: {event}"
            for src, events in TRANSITIONS.items() for event, dst in events.items()]


def uncovered_transitions(traj: Trajectory) -> list[str]:
    """定義されているのに、この軌跡では通らなかった遷移。"""
    visited = set(visited_edges(traj))
    return [edge for edge in all_edges() if edge not in visited]


if __name__ == "__main__":
    from agentkit.biztools import build_registry
    from agentkit.llm import ScriptedClient
    from runner import ResumableRunner
    from scenarios import RESEARCH

    TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
            "レポートにまとめ、報告会の会議室を予約してください")
    trajectory = ResumableRunner(ScriptedClient(RESEARCH), build_registry()).run(TASK)
    print(traj_to_mermaid(trajectory))
    print()
    print(f"通った遷移 {len(visited_edges(trajectory))} 本 / "
          f"定義 {len(all_edges())} 本 / "
          f"未通過 {len(uncovered_transitions(trajectory))} 本")
    for edge in uncovered_transitions(trajectory):
        print(f"  未通過: {edge}")
