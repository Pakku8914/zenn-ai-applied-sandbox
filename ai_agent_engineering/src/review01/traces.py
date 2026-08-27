#!/usr/bin/env python3
"""復習01で診断する6本の軌跡を決定的に作る。

    docker compose exec app python src/review01/traces.py

モデルの応答はすべて ScriptedClient（決定的オラクル）なので、何度実行しても
同じ軌跡になる。「症状は似ているのに原因が違う」6本を並べているのが要点である。

  A_normal          正常系（4手・done）
  B_stuck_loop      同じ検索を繰り返して打ち切られる（ツール結果はすべて成功）
  C_rephrase_loop   言い方を変えて悪い道具を叩き続ける（エラーが役に立たない）
  D_false_report    done なのに、やっていないことを報告する
  E_under_limit     正しく進んでいるのに上限が足りない
  F_actionable_loop 道具は良いエラーを返しているのに同じ誤りを繰り返す
"""

from __future__ import annotations

from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402

import agent_book_room as s02  # noqa: E402  (src/session02)
from badtools import build_bad_registry  # noqa: E402  (src/session04)
from goodtools import build_good_registry  # noqa: E402  (src/session04)
from measure import BAD_SCENARIO, reset_data  # noqa: E402  (src/session04)

# 冪等キーの形は S04 で決めた「日付-社員ID-金額」に従う
IDEM_KEY = "2026-08-15-EMP-003-68000"

REPORT_TASK = "今月の経費レポートを作ってください"
POLICY_TASK = "経費精算の規程を調べてください"
SUBMIT_TASK = "高橋 涼 の接待交際費 68,000 円を申請してください"

# 同じ検索を12回繰り返す。上限を上げても直らないことを見せたいので、
# シナリオ側の応答は上限より多めに用意しておく。
STUCK_LOOP = {
    "name": "review01_stuck_loop",
    "description": "同じ検索を繰り返す（ツール結果はすべて成功しているのに進まない）",
    "turns": [{"thought": "経費精算の規程を探す。",
               "calls": [{"name": "search_docs", "args": {"query": "経費", "limit": 1}}]}
              for _ in range(12)],
}

# 道具のエラーは「次の行動が決まる」形（許容値を全部返す）なのに、
# モデルが同じ区分で出し直し続ける軌跡。道具を直しても直らない側の例。
ACTIONABLE_LOOP = {
    "name": "review01_actionable_loop",
    "description": "許容値を返すエラーを受け取っても、同じ区分で出し直し続ける",
    "turns": [{"thought": f"接待交際費として申請する（{i + 1} 回目）。",
               "calls": [{"name": "submit_expense",
                          "args": {"employee": "高橋 涼", "amount": 68000,
                                   "category": "打ち上げ", "idempotency_key": IDEM_KEY,
                                   "note": f"9月商談の会食（{i + 1} 回目）"}}]}
              for i in range(4)],
}

# 同じ応答を、検証しないレジストリと検証するレジストリの両方に流すためのシナリオ。
# 「念のためもう一度」は現場で本当に起きる。冪等でない道具だと二重申請になる。
SAME_RESPONSES = {
    "name": "review01_same_responses",
    "description": "同じモデル応答。道具側の検証と冪等性だけを差し替えて比べる",
    "turns": [
        {"thought": "接待交際費として申請する。区分は「打ち上げ」でよいはずだ。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68000,
                             "category": "打ち上げ", "idempotency_key": IDEM_KEY}}]},
        {"thought": "念のため区分を「接待交際費」にして、もう一度申請しておく。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68000,
                             "category": "接待交際費", "idempotency_key": IDEM_KEY}}]},
        {"thought": "申請できたので報告する。",
         "final": "68,000円の接待交際費を申請しました。"},
    ],
}


@dataclass(frozen=True)
class Case:
    """診断の入力一式。

    軌跡だけでは原因が決まらないので、**どの道具を渡していたか**（registry）と
    **そのタスクで使ってよいツール**（allowed）、**設計時に見積もった手数**
    （needed_steps＝報告の1手を含む）も一緒に持ち歩く。
    """

    label: str
    traj: Trajectory
    registry: object
    allowed: frozenset
    needed_steps: int


def _run(scenario, registry, task: str, *, max_steps: int, task_id: str) -> Trajectory:
    return ReActAgent(ScriptedClient(scenario), registry,
                      max_steps=max_steps).run(task, task_id=task_id)


def build_cases() -> list[Case]:
    """6本の軌跡を作る。最初にデータを初期状態へ戻すので、何度呼んでも同じ結果になる。"""
    reset_data()
    biz = build_registry()
    bad = build_bad_registry()
    good = build_good_registry()
    report_tools = frozenset({"get_policy", "list_expenses", "read_file", "write_file"})
    return [
        Case("A_normal",
             _run("expense_report", biz, REPORT_TASK, max_steps=8, task_id="TASK-R01-A"),
             biz, report_tools, 4),
        Case("B_stuck_loop",
             _run(STUCK_LOOP, biz, POLICY_TASK, max_steps=6, task_id="TASK-R01-B"),
             biz, frozenset({"search_docs", "get_policy"}), 2),
        Case("C_rephrase_loop",
             _run(BAD_SCENARIO, bad, SUBMIT_TASK, max_steps=4, task_id="TASK-R01-C"),
             bad, frozenset(bad.names()), 2),
        Case("D_false_report",
             _run(s02.WRONG_TOOL_SCENARIO, biz, s02.CAPACITY_TASK,
                  max_steps=8, task_id="TASK-R01-D"),
             biz, frozenset({"get_policy", "book_room"}), 4),
        Case("E_under_limit",
             _run("expense_report", biz, REPORT_TASK, max_steps=3, task_id="TASK-R01-E"),
             biz, report_tools, 4),
        Case("F_actionable_loop",
             _run(ACTIONABLE_LOOP, good, SUBMIT_TASK, max_steps=4, task_id="TASK-R01-F"),
             good, frozenset({"submit_expense"}), 2),
    ]


def by_label() -> dict[str, Case]:
    return {case.label: case for case in build_cases()}


def main() -> None:
    cases = build_cases()
    print("=== 復習用の6本の軌跡（すべて決定的） ===")
    print("軌跡 | 停止理由 | 手数 | 呼び出し | 成功 | 失敗 | 最終回答")
    for case in cases:
        traj = case.traj
        results = [r for step in traj.steps for r in step.results]
        print(f"{case.label} | {traj.stop_reason} | {len(traj.steps)} | "
              f"{len(traj.tool_names)} | {sum(1 for r in results if r.ok)} | "
              f"{sum(1 for r in results if not r.ok)} | "
              f"{'あり' if traj.final else 'なし'}")
    tokens = [step.usage.get("input_tokens", 0) for step in cases[0].traj.steps]
    print(f"\nA_normal の入力トークンが単調に増えているか: "
          f"{all(a < b for a, b in zip(tokens, tokens[1:]))}")
    reset_data()


if __name__ == "__main__":
    main()
