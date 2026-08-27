#!/usr/bin/env python3
"""セッション16：コストの構造 — 手数 × 履歴長 × モデル単価。

    python src/session16/costshape.py

本モジュールが出す数値は2種類あり、**測定条件が違う**ので混ぜてはいけない。

  1. シナリオ別の表：業務データを初期化してから4シナリオを順に走らせる。
     経費レポート作成の入力は 1,022（経費が6件の状態）。
  2. 詳細モード：初期化 → 経費申請（5万円以上）→ 経費レポート作成 の順に走らせる。
     経費が7件になっているので入力は 1,061（13 → 129 → 374 → 545）。

`tools/traj_stats.py` の出力が「表の 1,022」と「ステップ別の合計 1,061」で
食い違うのはこの違いによる。**どちらも正しい実測値だが、足したり突き合わせたり
してはいけない。** 本モジュールは両方を別々の関数として提供し、混ざらないようにする。

なお、`tools/traj_stats.py` の5シナリオのうち `run_python_compute`（隔離実行）は
扱わない。tool-runner が起動していない環境でも同じ数値が出るようにするためである。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from prices import HIGH, PriceTable, shares, step_costs  # noqa: E402

# 表に載せるシナリオ（tools/traj_stats.py と同じ順序）
SCENARIOS: tuple[tuple[str, str, int], ...] = (
    ("expense_report", "経費レポート作成", 8),
    ("book_room_conflict", "会議室予約（競合あり）", 8),
    ("submit_expense_approval", "経費申請（5万円以上）", 8),
    ("max_steps_loop", "同じ検索を繰り返す", 6),
)

_make_data = None


def reset_data() -> None:
    """業務データを初期状態に戻す（S12〜S15 と同じ作法）。"""
    global _make_data
    if _make_data is None:
        import make_data  # noqa: PLC0415

        _make_data = make_data
    with contextlib.redirect_stdout(io.StringIO()):
        _make_data.main()


def run_one(scenario, label: str, max_steps: int = 8, *,
            tools=None, task_id: str | None = None, budget=None) -> Trajectory:
    """1シナリオを走らせる。`budget` には `.exceeded(traj)` を持つ物なら何でも渡せる。"""
    agent = ReActAgent(ScriptedClient(scenario), tools or build_registry(),
                       max_steps=max_steps, budget=budget)
    name = scenario if isinstance(scenario, str) else scenario.get("name", "inline")
    return agent.run(label, task_id=task_id or f"TASK-{name}")


def table_rows(table: PriceTable = HIGH) -> list[dict]:
    """シナリオ別の表（測定条件①：初期化してから4件を順に走らせる）。"""
    reset_data()
    rows = []
    for name, label, max_steps in SCENARIOS:
        traj = run_one(name, label, max_steps)
        total = traj.total_tokens
        rows.append({"シナリオ": label, "手数": len(traj.steps),
                     "ツール": len(traj.tool_names),
                     "in": total["input"], "out": total["output"],
                     "停止理由": traj.stop_reason,
                     "cu": table.cost(total["input"], total["output"])})
    return rows


def detail_trajectory() -> Trajectory:
    """詳細モードの軌跡（測定条件②：経費が7件の状態で経費レポート作成を走らせる）。

    ステップ別の入力トークンは 13 → 129 → 374 → 545、出力は 5 → 4 → 7 → 32 になる。
    """
    reset_data()
    run_one("submit_expense_approval", "経費申請（5万円以上）")
    return run_one("expense_report", "経費レポート作成", task_id="TASK-detail")


def step_rows(traj: Trajectory, table: PriceTable = HIGH) -> list[dict]:
    """ステップ別の内訳。**どのステップに乗っているか**を割合で出す。"""
    costs = step_costs(traj, table)
    pcts = shares(costs)
    rows = []
    for step, cost, pct in zip(traj.steps, costs, pcts):
        names = ", ".join(c.name for c in step.calls) or "（最終回答）"
        rows.append({"step": step.index,
                     "in": step.usage.get("input_tokens", 0),
                     "out": step.usage.get("output_tokens", 0),
                     "cu": cost, "share": pct, "action": names})
    return rows


def cumulative_inputs(traj: Trajectory) -> list[int]:
    """入力トークンの累計。手数に対して**二次的に**伸びることを見る。"""
    out, running = [], 0
    for step in traj.steps:
        running += step.usage.get("input_tokens", 0)
        out.append(running)
    return out


def fitted_per_step(traj: Trajectory) -> int:
    """1ステップあたり履歴が何トークン伸びたか（最初と最後から求める平均の増分）。"""
    ins = [s.usage.get("input_tokens", 0) for s in traj.steps]
    if len(ins) < 2:
        return 0
    return (ins[-1] - ins[0]) // (len(ins) - 1)


def model_input(n: int, base: int, per_step: int) -> int:
    """コストの式。入力の累計 = n·base + per_step·n(n−1)/2（**n の2次式**）。"""
    return n * base + per_step * n * (n - 1) // 2


# ---------------------------------------------------------------------------
# 会話履歴の組み立て（agentkit.loop._rebuild_messages と同じ手順を外から再現する）
# ---------------------------------------------------------------------------
def messages_for(traj: Trajectory, upto: int, head=None) -> list[dict]:
    """step[upto] の LLM 呼び出しに渡された会話履歴を復元する。

    `head` に「呼ばれるたびに違う文字列を返す関数」を渡すと、先頭が毎回変わる
    履歴になる（＝前方一致が壊れる。やってはいけない例）。
    """
    messages: list[dict] = []
    if head is not None:
        messages.append({"role": "system", "content": head(upto)})
    messages.append({"role": "user", "content": traj.task})
    for s in traj.steps[:upto]:
        if not s.calls:
            continue
        messages.append({
            "role": "assistant",
            "content": ([{"type": "text", "text": s.thought}] if s.thought else [])
            + [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args}
               for c in s.calls],
        })
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": r.call_id,
                         "content": r.content if r.ok else (r.error or ""),
                         "is_error": not r.ok} for r in s.results],
        })
    return messages


def prompt_tokens(messages: list[dict]) -> int:
    """近似トークン数（プロンプトの文字数 ÷ 3・比較用）。ScriptedClient と同じ式。"""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 3


def cacheable_tokens(traj: Trajectory, head=None) -> int:
    """前方一致で再利用できる入力トークンの合計。

    履歴は「付け足すだけ」なので、step[i] のプロンプトは step[i-1] のプロンプトを
    まるごと前方に含む。したがって再利用できるのは step[i-1] の入力そのものである。
    先頭に毎回変わる文字列を1行入れるだけで、これが **0 になる**。
    """
    prompts = [messages_for(traj, i, head) for i in range(len(traj.steps))]
    total = 0
    for prev, cur in zip(prompts, prompts[1:]):
        common = 0
        for a, b in zip(prev, cur):
            if a != b:
                break
            common += len(json.dumps(a, ensure_ascii=False))
        total += common // 3
    return total


def unstable_head(index: int) -> str:
    """やってはいけない例：先頭に毎回違う時刻を入れる（S03 の FixedClock の裏返し）。"""
    return f"現在時刻: 2026-08-15T09:0{index}:00+09:00"


def main() -> None:
    print("=== ① シナリオ別（初期化してから4件を順に実行・単価表は上位）===")
    print(f"{'シナリオ':<26}{'手数':>5}{'ツール':>7}{'in':>8}{'out':>6}"
          f"{'コスト(cu)':>12}  停止理由")
    rows = table_rows()
    for r in rows:
        print(f"{r['シナリオ']:<26}{r['手数']:>5}{r['ツール']:>7}{r['in']:>8}"
              f"{r['out']:>6}{r['cu']:>12}  {r['停止理由']}")
    worst = max(rows, key=lambda r: r["cu"])
    best = rows[0]
    print(f"合計 {sum(r['cu'] for r in rows)} cu ／ 最も高いのは「{worst['シナリオ']}」で "
          f"{worst['cu'] / best['cu']:.2f} 倍。**成果はゼロ**（停止理由 {worst['停止理由']}）。")
    print(f"手数は {worst['手数'] / best['手数']:.1f} 倍なのに入力は "
          f"{worst['in'] / best['in']:.2f} 倍。コストは手数に比例しない。")

    traj = detail_trajectory()
    ins = [s.usage.get("input_tokens", 0) for s in traj.steps]
    print("\n=== ② 詳細モード（経費7件の状態。①の 1,022 とは条件が違う）===")
    print(f"{'step':>5}{'in':>8}{'out':>6}{'cu':>8}{'割合':>8}  行動")
    for r in step_rows(traj):
        print(f"{r['step']:>5}{r['in']:>8}{r['out']:>6}{r['cu']:>8}"
              f"{r['share']:>7.1f}%  {r['action']}")
    print(f"入力の累計: {cumulative_inputs(traj)}（単調増加＝履歴が毎回全部送られる）")

    per_step = fitted_per_step(traj)
    n = len(ins)
    print(f"\n式にすると: 入力の累計 ≈ n×{ins[0]} + {per_step}×n(n−1)/2")
    print(f"  n={n}: 予測 {model_input(n, ins[0], per_step)} / 実測 {sum(ins)}")
    print(f"  n={n * 2}: 予測 {model_input(n * 2, ins[0], per_step)}"
          f"（手数2倍でコストは "
          f"{model_input(n * 2, ins[0], per_step) / model_input(n, ins[0], per_step):.2f} 倍）")

    print("\n=== ③ 前方一致でキャッシュできる量 ===")
    for i, step in enumerate(traj.steps):
        rebuilt = prompt_tokens(messages_for(traj, i))
        mark = "一致" if rebuilt == step.usage.get("input_tokens", 0) else "不一致"
        print(f"  step[{i}] 復元={rebuilt} 実測={step.usage.get('input_tokens', 0)} → {mark}")
    stable = cacheable_tokens(traj)
    print(f"再利用できる入力: {stable} / {sum(ins)}"
          f"（新しく払うのは {sum(ins) - stable} ＝ 最後のステップの入力と同じ）")
    print(f"先頭に毎回違う時刻を1行入れると: {cacheable_tokens(traj, unstable_head)}"
          "（前方一致が全ステップで壊れる）")

    reset_data()


if __name__ == "__main__":
    main()
