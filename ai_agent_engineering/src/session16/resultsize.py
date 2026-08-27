#!/usr/bin/env python3
"""セッション16：ツール結果は「残りのステップ数」だけ課金される。

    python src/session16/resultsize.py

ツール結果は1回返って終わりではない。**そのあとの全ステップで毎回送り直される。**
だから同じ 300 文字でも、早いステップで返ってきた結果ほど高くつく。

実験は決定的にできる。ツール結果の末尾に 3 の倍数の文字数（既定 300 文字）を足すと、
近似トークン（文字数 ÷ 3）はちょうど 100 増える。切り捨てが起きないので、
増分は「100 × 影響するステップ数」と**1トークンの誤差もなく**一致する。

S04 でツール結果そのものを 近似346 → 34 に削り、S07 で外部化して
253記録/近似2,783 → 27記録/近似297 に落としたのは、この掛け算を小さくするためである。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _d in (ROOT, HERE, ROOT / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.tools import ToolRegistry  # noqa: E402
from costshape import reset_data, run_one  # noqa: E402

PAD = 300  # 3 で割り切れる文字数にしてある（近似トークンがちょうど 100 増える）

# 経費レポート作成の軌跡で、どのツールが何手目に呼ばれ、そのあと何ステップ残るか
TARGETS: tuple[tuple[str, int, int], ...] = (
    ("get_policy", 0, 3),
    ("list_expenses", 1, 2),
    ("write_file", 2, 1),
)


def _padded(fn, pad: int):
    """ツール結果の末尾に pad 文字を足すラッパ（中身は変えない）。"""
    def wrapped(**kwargs):
        return f"{fn(**kwargs)}{'x' * pad}"

    return wrapped


def padded_registry(target: str, pad: int = PAD) -> ToolRegistry:
    """指定したツールの結果だけを太らせたレジストリ。`agentkit` は変更しない。"""
    base = build_registry()
    if base.get(target) is None:
        raise ValueError(f"ツール '{target}' がありません。使えるツール: {base.names()}")
    tools = []
    for name in base.names():
        tool = base.get(name)
        tools.append(replace(tool, fn=_padded(tool.fn, pad)) if name == target else tool)
    return ToolRegistry(tools)


def slim_expenses(status: str = "all") -> str:
    """`list_expenses` の代わりに、レポートに要る情報だけを返す（S04 の作法）。

    返すのは「件数・合計・区分ごとの内訳・注記のある申請だけ」。
    全件の表を返さないのは、その表が**残りのステップぶん再送される**ため。
    """
    import json  # noqa: PLC0415

    from agentkit.biztools import DATA  # noqa: PLC0415

    rows = [json.loads(line) for line in (DATA / "expenses.jsonl").open(encoding="utf-8")
            if line.strip()]
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    flagged = [f"{r['expense_id']}({r['note']})" for r in rows if r["note"]]
    lines = [f"件数 {len(rows)} / 合計 {sum(r['amount'] for r in rows)}円",
             " ".join(f"{k}:{v}" for k, v in sorted(by_cat.items())),
             "注記あり: " + (" ".join(flagged) if flagged else "なし")]
    return "\n".join(lines)


def slim_registry() -> ToolRegistry:
    """`list_expenses` を絞り込み版に差し替えたレジストリ。"""
    base = build_registry()
    tools = []
    for name in base.names():
        tool = base.get(name)
        tools.append(replace(tool, fn=slim_expenses) if name == "list_expenses" else tool)
    return ToolRegistry(tools)


def _detail_base() -> None:
    """詳細モードの前提（経費7件）を作る。以降このデータのまま何度でも走らせられる。"""
    reset_data()
    run_one("submit_expense_approval", "経費申請（5万円以上）")


def pad_rows(pad: int = PAD) -> list[dict]:
    """「どのステップの結果を太らせたか」ごとの入力トークンの増え方。"""
    _detail_base()
    base = run_one("expense_report", "経費レポート作成", task_id="TASK-detail")
    base_in = base.total_tokens["input"]
    rows = [{"太らせたツール": "（なし・基準）", "呼ばれた手": "-", "残りステップ": 0,
             "in": base_in, "増分": 0, "理論値": 0,
             "ステップ別": [s.usage["input_tokens"] for s in base.steps]}]
    for name, at, remaining in TARGETS:
        traj = run_one("expense_report", "経費レポート作成",
                       tools=padded_registry(name, pad), task_id=f"TASK-pad-{name}")
        total = traj.total_tokens["input"]
        rows.append({"太らせたツール": name, "呼ばれた手": at, "残りステップ": remaining,
                     "in": total, "増分": total - base_in,
                     "理論値": pad // 3 * remaining,
                     "ステップ別": [s.usage["input_tokens"] for s in traj.steps]})
    return rows


def slim_row() -> dict:
    """ツール結果を実際に短くしたときの効果（結果そのものと軌跡全体の両方を見る）。"""
    _detail_base()
    base = run_one("expense_report", "経費レポート作成", task_id="TASK-detail")
    slim = run_one("expense_report", "経費レポート作成",
                   tools=slim_registry(), task_id="TASK-slim")
    full_result = base.steps[1].results[0].content
    slim_result = slim.steps[1].results[0].content
    return {"結果の文字数": (len(full_result), len(slim_result)),
            "結果の近似トークン": (len(full_result) // 3, len(slim_result) // 3),
            "入力の合計": (base.total_tokens["input"], slim.total_tokens["input"]),
            "ツール列": (base.tool_names, slim.tool_names),
            "停止理由": (base.stop_reason, slim.stop_reason)}


def main() -> None:
    rows = pad_rows()
    print(f"=== ツール結果を {PAD} 文字（近似 {PAD // 3} トークン）太らせる ===")
    print(f"{'太らせたツール':<20}{'呼ばれた手':>10}{'残りステップ':>12}"
          f"{'入力合計':>10}{'増分':>7}{'理論値':>8}  ステップ別")
    for r in rows:
        print(f"{r['太らせたツール']:<20}{str(r['呼ばれた手']):>10}{r['残りステップ']:>12}"
              f"{r['in']:>10}{r['増分']:>7}{r['理論値']:>8}  {r['ステップ別']}")
    print("→ 同じ 300 文字でも、**早く返ってきた結果ほど高い**（3倍 : 2倍 : 1倍）。")

    slim = slim_row()
    print("\n=== 逆に、ツール結果を短くしたとき（list_expenses を絞り込み版に差し替え）===")
    print(f"結果そのもの: {slim['結果の文字数'][0]} 文字（近似 {slim['結果の近似トークン'][0]}）"
          f" → {slim['結果の文字数'][1]} 文字（近似 {slim['結果の近似トークン'][1]}）")
    print(f"軌跡全体の入力: {slim['入力の合計'][0]} → {slim['入力の合計'][1]}"
          f"（{slim['入力の合計'][0] - slim['入力の合計'][1]} 減）")
    print(f"ツール列は変わらない: {slim['ツール列'][0] == slim['ツール列'][1]} "
          f"／ 停止理由: {slim['停止理由'][1]}")

    reset_data()


if __name__ == "__main__":
    main()
