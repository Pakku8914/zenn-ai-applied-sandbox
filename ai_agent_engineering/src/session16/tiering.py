#!/usr/bin/env python3
"""セッション16：モデル階層 — 判断は上位、整形は下位。

    python src/session16/tiering.py

全ステップを最上位モデルで回すのはアンチパターンである。エージェントのステップには
「次に何をするか決める」ステップと「決まったことを文章にする」ステップが混ざっており、
後者は下位モデルで足りることが多い。しかも**後ろのステップほど履歴が長い**ので、
最後の1ステップを下位に回すだけで効き方が大きい。

:::注意:::
本書の LLM は決定的オラクル（ScriptedClient）なので、**下位に落としても軌跡は変わらない**。
これは教材上の仮定であって、実モデルでは変わりうる。だから格下げの判断は必ず
軌跡テスト（S13 の task_success / tool_choice_accuracy）で確かめること。
その「変わってしまった場合」を DEGRADED として用意してある。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.eval import ExpectedTrajectory, task_success, tool_choice_accuracy  # noqa: E402
from costshape import detail_trajectory, run_one  # noqa: E402
from prices import HIGH, LOW  # noqa: E402

# 経費レポート作成に期待する軌跡（S13 の宣言をそのまま使う）
EXPECTED = ExpectedTrajectory(
    task_id="TASK-detail",
    tools=["get_policy", "list_expenses", "write_file"],
    ordered=True,
    forbidden_tools=["send_message"],
    final_contains=["report.md", "EXP-0002"],
    max_steps=4,
)


def role_of(step) -> str:
    """ステップの役割。ツールを選ぶなら「判断」、最終回答だけなら「整形」。"""
    return "判断" if step.calls else "整形"


def route_all_high(index: int, step, spent: int):
    """アンチパターン：全ステップを最上位で回す。"""
    return HIGH


def route_by_role(index: int, step, spent: int):
    """役割で振り分ける。判断は上位、整形は下位。"""
    return HIGH if step.calls else LOW


def route_threshold(threshold: int):
    """累計コストが閾値を超えたら、以降を下位に格下げする（動的な格下げ）。"""
    def route(index: int, step, spent: int):
        return LOW if spent >= threshold else HIGH

    return route


def tier_rows(traj, route=route_by_role) -> list[dict]:
    """ステップごとに、どの階層でいくら払ったかを並べる。"""
    rows, spent = [], 0
    for index, step in enumerate(traj.steps):
        table = route(index, step, spent)
        cost = table.cost(step.usage.get("input_tokens", 0),
                          step.usage.get("output_tokens", 0))
        spent += cost
        rows.append({"step": index, "役割": role_of(step), "階層": table.label,
                     "in": step.usage.get("input_tokens", 0),
                     "out": step.usage.get("output_tokens", 0),
                     "cu": cost, "累計": spent})
    return rows


def tiered_cost(traj, route=route_by_role) -> int:
    """振り分けた結果の合計コスト（cu）。"""
    rows = tier_rows(traj, route)
    return rows[-1]["累計"] if rows else 0


# ---------------------------------------------------------------------------
# 「格下げしたら挙動が変わった」場合（実モデルで起きるほうの現実）
# ---------------------------------------------------------------------------
DEGRADED = {
    "name": "expense_report_degraded",
    "description": "下位モデルに落としたら、余計な検索が1回混ざった軌跡",
    "turns": [
        {"thought": "まず経費精算の規程を確認する。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "念のため関連する文書も検索しておく。",
         "calls": [{"name": "search_docs", "args": {"query": "経費"}}]},
        {"thought": "次に申請一覧を取得する。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
        {"thought": "集計してレポートを作り、作業領域に保存する。",
         "calls": [{"name": "write_file", "args": {
             "path": "report.md",
             "content": "# 2026年8月 経費レポート\n\n- 交通費: 7,600円\n"
                        "- 接待交際費: 120,000円\n- 備品: 12,800円\n- 出張旅費: 145,000円\n\n"
                        "## 規程違反の注記\n- EXP-0002: 5万円以上だが事前承認なし\n"
                        "- EXP-0004: 申請が期限（10日）を超過\n"}}]},
        {"thought": "レポートを保存したので完了を報告する。",
         "final": "report.md に2026年8月の経費レポートを作成しました。"
                  "規程違反が2件あります（EXP-0002 の事前承認なし、EXP-0004 の期限超過）。"},
    ],
}


def degraded_trajectory():
    """格下げして挙動が変わった軌跡（手数が1つ増える）。"""
    return run_one(DEGRADED, "経費レポート作成", task_id="TASK-degraded")


def precision(traj, expected: ExpectedTrajectory = EXPECTED) -> float:
    """適合率：呼んだツールのうち、期待に含まれていたものの割合（S13 の続き）。

    再現率（＝ tool_choice_accuracy）は「必要なものを呼べたか」しか見ない。
    余計な呼び出しはコストになるので、適合率も並べて見る。
    """
    got = traj.tool_names
    if not got:
        return 1.0
    return sum(1 for name in got if name in expected.tools) / len(got)


def compare_rows() -> list[dict]:
    """健全な階層化と、挙動が変わってしまった格下げを並べる。"""
    base = detail_trajectory()
    bad = degraded_trajectory()
    out = []
    for label, traj, route in (("① 全部を上位で回す", base, route_all_high),
                               ("② 役割で振り分ける", base, route_by_role),
                               ("③ 累計 5,000 cu で格下げ", base, route_threshold(5_000)),
                               ("④ 格下げで挙動が変わった", bad, route_by_role)):
        out.append({"方式": label, "手数": len(traj.steps),
                    "cu": tiered_cost(traj, route),
                    "成功": task_success(traj, EXPECTED),
                    "再現率": tool_choice_accuracy(traj, EXPECTED),
                    "適合率": precision(traj),
                    "ツール列": traj.tool_names})
    return out


def main() -> None:
    base = detail_trajectory()
    print("=== ステップごとの役割と階層（詳細モードの軌跡）===")
    print(f"{'step':>5}{'役割':>6}{'階層':>18}{'in':>7}{'out':>6}{'cu':>7}{'累計':>8}")
    for r in tier_rows(base, route_by_role):
        print(f"{r['step']:>5}{r['役割']:>6}{r['階層']:>18}{r['in']:>7}"
              f"{r['out']:>6}{r['cu']:>7}{r['累計']:>8}")

    high = tiered_cost(base, route_all_high)
    print("\n=== 方式ごとの比較 ===")
    print(f"{'方式':<26}{'手数':>5}{'cu':>8}{'削減':>8}{'成功':>7}{'再現率':>8}{'適合率':>8}")
    for r in compare_rows():
        cut = f"{(high - r['cu']) / high * 100:.1f}%" if r["cu"] <= high else "増える"
        print(f"{r['方式']:<26}{r['手数']:>5}{r['cu']:>8}{cut:>8}"
              f"{'○' if r['成功'] else '×':>6}{r['再現率']:>8.3f}{r['適合率']:>8.3f}")
    print("→ ②③ は軌跡が1文字も変わらないまま安くなる（削減はどちらも同じ）。")
    print("→ ④ は下位単価で計算しているのに手数が1つ増え、成功判定に落ちる。"
          "適合率は 1.000 → 0.750。**安くなったかどうかだけを見てはいけない**。")


if __name__ == "__main__":
    main()
