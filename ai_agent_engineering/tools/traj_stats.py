#!/usr/bin/env python3
"""シナリオごとの手数・ツール呼び出し・トークン量を出す。

本文に書く「ステップ数」「トークン内訳」の出典。
トークン数は決定的な近似値（3文字=1トークン相当）なので、**絶対値ではなく比較に使う**。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402

SCENARIOS = [
    ("expense_report", "経費レポート作成", 8),
    ("book_room_conflict", "会議室予約（競合あり）", 8),
    ("submit_expense_approval", "経費申請（5万円以上）", 8),
    ("run_python_compute", "隔離実行で集計", 8),
    ("max_steps_loop", "同じ検索を繰り返す", 6),
]


def main() -> None:
    print(f"{'シナリオ':<28}{'手数':>5}{'ツール':>7}{'in':>9}{'out':>7}{'停止理由':>18}")
    print("-" * 78)
    for name, label, max_steps in SCENARIOS:
        agent = ReActAgent(ScriptedClient(name), build_registry(), max_steps=max_steps)
        traj = agent.run(label, task_id=f"TASK-{name}")
        total = traj.total_tokens
        print(f"{label:<28}{len(traj.steps):>5}{len(traj.tool_names):>7}"
              f"{total['input']:>9}{total['output']:>7}{traj.stop_reason:>18}")

    print("\n=== ステップ別の入力トークン（履歴が伸びる様子）===")
    # 注意：ここは上の集計ループのあとに走る。集計中に submit_expense_approval が
    # 経費を1件追加しているため list_expenses が7件を返し、合計は上の表の
    # 「経費レポート作成 in」より大きくなる（1,061 対 1,022）。
    # 同じ数字にはならないので、2つを足したり引き比べたりしないこと。
    # 上の表と揃えたいときは、この行の前に tools/make_data.py を実行する。
    agent = ReActAgent(ScriptedClient("expense_report"), build_registry())
    traj = agent.run("経費レポート作成", task_id="TASK-detail")
    print(f"{'step':>5}{'in':>9}{'out':>7}  呼んだツール")
    for s in traj.steps:
        names = ", ".join(c.name for c in s.calls) or "（最終回答）"
        print(f"{s.index:>5}{s.usage.get('input_tokens', 0):>9}"
              f"{s.usage.get('output_tokens', 0):>7}  {names}")


if __name__ == "__main__":
    main()
