#!/usr/bin/env python3
"""セッション16：コスト上限と、超えたときの振る舞い。

    python src/session16/capguard.py

`agentkit.loop.Budget` は**事後判定**である。ステップを実行したあとに合計を見て、
超えていたら次のステップに進まない。ところがエージェントは**後ろのステップほど重い**
ので、事後判定では「上限の直前で通過して、最後の1ステップで倍払う」ことが起きる。

そこで本章では、`.exceeded(traj)` を持つだけで `ReActAgent` に差し込める性質を使い、
**次の1ステップの見積もりを足してから判定する**上限を外側に作る。`agentkit` は
1行も変更しない。

上限は「止める」だけで、タスクは完了しない。だから超過時の振る舞い（打ち切り／
格下げ／人間に渡す）を必ずセットで決める。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.loop import Budget  # noqa: E402
from costshape import detail_trajectory, reset_data, run_one, table_rows  # noqa: E402
from prices import HIGH, PriceTable, traj_cost  # noqa: E402
from tiering import route_threshold, tiered_cost  # noqa: E402

LIMITS = (400, 520, 1_000, 1_200)      # 近似入力トークンの上限（節7の比較表）
TASK_CU_LIMIT = 10_000                 # 1タスクのコスト上限（cu）
PER_TASK_LIMIT = 15_000                # 1タスクの上限（1日の設計に組み込むほう）
DAILY_LIMIT = 50_000                   # 1日の上限（cu）

HANDOFF_SECTIONS = ("頼まれたこと", "止まった理由", "済んだ操作", "残っている操作", "次にやること")


def estimate_next_input(traj) -> int:
    """次のステップの入力トークンの見積もり。

    直近の入力に「1ステップあたりの平均の伸び」を足すだけ。**荒くてよい**。
    荒くても、事後判定（見積もり 0）よりはるかにましである。
    """
    ins = [s.usage.get("input_tokens", 0) for s in traj.steps]
    if not ins:
        return 0
    if len(ins) == 1:
        return ins[-1]
    diffs = [b - a for a, b in zip(ins, ins[1:])]
    return ins[-1] + int(sum(diffs) / len(diffs))


@dataclass
class CostGuard:
    """入力トークンの上限。**見積もりを足してから**判定する。

    `ReActAgent(budget=...)` は `.exceeded(traj)` を呼ぶだけなので、
    `Budget` の代わりにそのまま差し込める（agentkit を変更しない拡張点）。
    """

    max_input_tokens: int

    def exceeded(self, traj) -> bool:
        return traj.total_tokens["input"] + estimate_next_input(traj) > self.max_input_tokens


@dataclass
class CostUnitGuard:
    """金額（コスト単位）で切る上限。見積もりは「次の入力 × 単価 ＋ 直近最大の出力 × 単価」。"""

    max_cost: int
    table: PriceTable = HIGH

    def exceeded(self, traj) -> bool:
        spent = traj_cost(traj, self.table)
        outs = [s.usage.get("output_tokens", 0) for s in traj.steps]
        est = self.table.cost(estimate_next_input(traj), max(outs) if outs else 0)
        return spent + est > self.max_cost


def input_budget(limit: int) -> Budget:
    """入力トークンだけを見る Budget（他の上限は事実上無効にする）。"""
    return Budget(max_input_tokens=limit, max_output_tokens=10 ** 9, max_tool_calls=10 ** 9)


def limit_rows(limits: tuple[int, ...] = LIMITS) -> list[dict]:
    """同じタスクを、事後判定と見積もり判定のそれぞれの上限で走らせて比べる。"""
    detail_trajectory()          # 経費7件の状態を作る（以降このデータのまま）
    rows = []
    for limit in limits:
        after = run_one("expense_report", "経費レポート作成",
                        task_id="TASK-budget", budget=input_budget(limit))
        guard = run_one("expense_report", "経費レポート作成",
                        task_id="TASK-guard", budget=CostGuard(limit))
        rows.append({
            "上限": limit,
            "事後": {"手数": len(after.steps), "in": after.total_tokens["input"],
                     "停止理由": after.stop_reason,
                     "上限比": after.total_tokens["input"] / limit * 100},
            "見積": {"手数": len(guard.steps), "in": guard.total_tokens["input"],
                     "停止理由": guard.stop_reason,
                     "上限比": guard.total_tokens["input"] / limit * 100},
        })
    return rows


def strictness() -> dict:
    """`>` と `>=` の1文字の差。`Budget` は「超えたら」、S11 の RunLimits は「達したら」。"""
    traj = detail_trajectory()
    total = traj.total_tokens["input"]
    return {"合計": total,
            "上限＝合計（Budget の `>`）": input_budget(total).exceeded(traj),
            "上限＝合計−1": input_budget(total - 1).exceeded(traj)}


# ---------------------------------------------------------------------------
# 超過時の振る舞い
# ---------------------------------------------------------------------------
def handoff_note(traj, limit: int, spent: int, remaining: str) -> str:
    """人に渡すための引き継ぎ書（S15 の作法と同じ5項目）。"""
    return "\n".join([
        "コスト上限に達したため、ここから先は人に引き継ぎます。",
        f"- 頼まれたこと: {traj.task}",
        f"- 止まった理由: 1タスクの上限 {limit} cu に対して {spent} cu を消費"
        f"（{spent / limit * 100:.1f}%）。次の1ステップで超える見込みでした",
        f"- 済んだ操作: {', '.join(traj.tool_names) or 'なし'}",
        f"- 残っている操作: {remaining}",
        "- 次にやること: 残っている操作を人が実行するか、"
        "整形だけを下位モデルに回して再開する",
    ])


def check_handoff(note: str) -> list[str]:
    """引き継ぎ書に必要な項目がそろっているか（足りない項目名を返す）。"""
    return [s for s in HANDOFF_SECTIONS if s not in note]


def behaviour_rows(limit: int = TASK_CU_LIMIT) -> list[dict]:
    """上限 limit cu を超えそうなときの3つの振る舞いを並べる。"""
    base = detail_trajectory()                       # 上限なしなら 4手で完走する
    stopped = run_one("expense_report", "経費レポート作成",
                      task_id="TASK-cap", budget=CostUnitGuard(limit))
    stopped_cu = traj_cost(stopped, HIGH)
    down_cu = tiered_cost(base, route_threshold(limit // 2))
    # 打ち切った時点で write_file は実行済み。**副作用は出ているのに報告が無い**という
    # 最も困る状態になる。だからこの状態は黙って捨てず、人に渡す。
    note = handoff_note(stopped, limit, stopped_cu, "最終回答（利用者への報告）")
    return [
        {"振る舞い": "打ち切り（fail）", "手数": len(stopped.steps), "cu": stopped_cu,
         "停止理由": stopped.stop_reason,
         "成果": "report.md は保存済み・利用者への報告なし", "note": ""},
        {"振る舞い": "格下げ（downgrade）", "手数": len(base.steps), "cu": down_cu,
         "停止理由": base.stop_reason, "成果": "報告まで完了", "note": ""},
        {"振る舞い": "人間に渡す（handoff）", "手数": len(stopped.steps), "cu": stopped_cu,
         "停止理由": stopped.stop_reason, "成果": "同じ状態＋引き継ぎ書（残り1手の指示）",
         "note": note},
    ]


# ---------------------------------------------------------------------------
# 3層の上限（1タスク・1ユーザー・1日）
# ---------------------------------------------------------------------------
@dataclass
class Ledger:
    """1日ぶんの台帳。1タスク上限を置くと、1日の上限が守れるようになる。"""

    daily_limit: int = DAILY_LIMIT
    per_task_limit: int | None = None
    spent: int = 0
    rows: list[dict] = field(default_factory=list)

    def charge(self, name: str, cost: int) -> dict:
        billed = min(cost, self.per_task_limit) if self.per_task_limit else cost
        capped = billed < cost
        self.spent += billed
        row = {"タスク": name, "単価": cost, "請求": billed, "打ち切り": capped,
               "累計": self.spent, "超過": self.spent > self.daily_limit}
        self.rows.append(row)
        return row


def daily_rows(costs: list[tuple[str, int]], per_task_limit: int | None = None,
               daily_limit: int = DAILY_LIMIT) -> list[dict]:
    ledger = Ledger(daily_limit=daily_limit, per_task_limit=per_task_limit)
    for name, cost in costs:
        ledger.charge(name, cost)
    return ledger.rows


def admit_rows(costs: list[tuple[str, int]], daily_limit: int = DAILY_LIMIT,
               per_task_limit: int | None = None) -> list[dict]:
    """1日の上限に対して、来た順に受け付けるか拒否するかを決める。

    1タスク上限が無いと、**どのタスクが拒否されるかが到着順で決まる**。
    暴走した1件が先に来ると、そのあとの正常なタスクが締め出される。
    """
    spent, rows = 0, []
    for name, cost in costs:
        billed = min(cost, per_task_limit) if per_task_limit else cost
        if spent + billed > daily_limit:
            rows.append({"タスク": name, "請求": 0, "累計": spent, "判定": "拒否"})
            continue
        spent += billed
        rows.append({"タスク": name, "請求": billed, "累計": spent,
                     "判定": "打ち切り" if billed < cost else "実行"})
    return rows


def capped_runaway(cap: int = PER_TASK_LIMIT) -> dict:
    """暴走した1件に1タスク上限をかけたときの実消費。"""
    reset_data()
    free = run_one("max_steps_loop", "同じ検索を繰り返す", 6)
    capped = run_one("max_steps_loop", "同じ検索を繰り返す", 6,
                     task_id="TASK-capped", budget=CostUnitGuard(cap))
    return {"上限なし": {"手数": len(free.steps), "cu": traj_cost(free, HIGH),
                         "停止理由": free.stop_reason},
            "上限あり": {"手数": len(capped.steps), "cu": traj_cost(capped, HIGH),
                         "停止理由": capped.stop_reason},
            "上限": cap}


def main() -> None:
    print("=== ① 事後判定（Budget）と見積もり判定（CostGuard）===")
    print(f"{'上限':>6} | {'事後: 手数/入力/停止理由/上限比':<34} | 見積: 手数/入力/停止理由/上限比")
    for r in limit_rows():
        a, b = r["事後"], r["見積"]
        left = f"{a['手数']}手 / {a['in']} / {a['停止理由']} / {a['上限比']:.1f}%"
        right = f"{b['手数']}手 / {b['in']} / {b['停止理由']} / {b['上限比']:.1f}%"
        print(f"{r['上限']:>6} | {left:<34} | {right}")
    print("→ 上限 520 のつもりで 1,061 払うのが事後判定。最後の1ステップが最も重いため。")

    s = strictness()
    print(f"\n=== ② `>` と `>=` の1文字（合計 {s['合計']}）===")
    print(f"上限を合計と同じ値にした Budget は止まるか: {s['上限＝合計（Budget の `>`）']}"
          "（`>` なので止まらない）")
    print(f"上限を合計−1 にすると: {s['上限＝合計−1']}")
    print("→ S11 の RunLimits は「達したら止める」（`>=`）。混在させないこと。")

    print(f"\n=== ③ 上限 {TASK_CU_LIMIT} cu を超えそうなときの3つの振る舞い ===")
    print(f"{'振る舞い':<24}{'手数':>5}{'cu':>8}{'停止理由':>12}  成果")
    rows = behaviour_rows()
    for r in rows:
        print(f"{r['振る舞い']:<24}{r['手数']:>5}{r['cu']:>8}{r['停止理由']:>12}  {r['成果']}")
    print("→ 上限内で最も成果が大きいのは格下げ。打ち切りは最後の手段。")
    print("\n--- 引き継ぎ書 ---")
    print(rows[2]["note"])
    print(f"不足している項目: {check_handoff(rows[2]['note']) or 'なし'}")

    print(f"\n=== ④ 1日の上限 {DAILY_LIMIT} cu ===")
    costs = [(r["シナリオ"], r["cu"]) for r in table_rows()]
    for label, per_task in (("1タスク上限なし", None), (f"1タスク上限 {PER_TASK_LIMIT} cu", PER_TASK_LIMIT)):
        print(f"\n[{label}]")
        print(f"{'タスク':<26}{'単価':>8}{'請求':>8}{'累計':>9}  判定")
        for row in daily_rows(costs, per_task_limit=per_task):
            verdict = "超過" if row["超過"] else ("打ち切り" if row["打ち切り"] else "OK")
            print(f"{row['タスク']:<26}{row['単価']:>8}{row['請求']:>8}{row['累計']:>9}  {verdict}")

    cap = capped_runaway()
    print(f"\n=== ⑤ 暴走した1件に 1タスク上限 {cap['上限']} cu をかける ===")
    print(f"上限なし: {cap['上限なし']['手数']}手 / {cap['上限なし']['cu']} cu / "
          f"{cap['上限なし']['停止理由']}")
    print(f"上限あり: {cap['上限あり']['手数']}手 / {cap['上限あり']['cu']} cu / "
          f"{cap['上限あり']['停止理由']}")

    reset_data()


if __name__ == "__main__":
    main()
