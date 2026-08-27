#!/usr/bin/env python3
"""セッション14：内訳 — どのステップに何が乗っているかをステップ単位で出す。

    python src/session14/breakdown.py

内訳には2つの落とし穴がある。

  1. **単価表に依存する。** 「LLM が支配的」という結論は、LLM の単価が高い環境での
     結論でしかない。単価表を差し替えると1位が入れ替わる。だから単価表を記録に含める。
  2. **未計測を 0 として足してしまう。** 計測していない区間は 0 ms ではない。
     本章の単価表は宣言値であり、実測は隔離実行の 115 ms だけである。

コストは近似トークン数（プロンプトの文字数 ÷ 3・比較用）で見る。絶対値ではなく
「ステップごとに増える」という形を見る（S03・S16）。
"""

from __future__ import annotations

from spanlog import (UNITS_A, UNITS_B, LatencyUnits, Trajectory,  # noqa: E402
                     reset_data, run_case, spans_from_trajectory)


def step_rows(traj: Trajectory, units: LatencyUnits) -> list[dict]:
    """ステップ単位の内訳。所要は「回数 × 単価」で決定的に出す。"""
    spans = spans_from_trajectory(traj, units)
    total = spans[0].ms or 1
    rows = []
    for step in spans:
        if step.kind != "step":
            continue
        children = [s for s in spans if s.parent_id == step.span_id]
        rows.append({
            "step": step.name,
            "llm": sum(1 for s in children if s.kind == "llm"),
            "tool": sum(1 for s in children if s.kind == "tool"),
            "ms": step.ms,
            "share": step.ms / total * 100,
        })
    return rows


def kind_totals(traj: Trajectory, units: LatencyUnits) -> dict:
    """種別ごとの合計と、最も寄与の大きい種別。"""
    spans = spans_from_trajectory(traj, units)
    total = spans[0].ms or 1
    llm_ms = sum(s.ms for s in spans if s.kind == "llm")
    tool_ms = sum(s.ms for s in spans if s.kind == "tool")
    return {"label": units.label, "llm": llm_ms, "tool": tool_ms, "total": total,
            "llm_share": llm_ms / total * 100, "tool_share": tool_ms / total * 100,
            "top": "llm" if llm_ms >= tool_ms else "tool"}


def token_shape(traj: Trajectory) -> dict:
    """入力トークンの形。**絶対値ではなく増え方**を見る（近似トークン数・比較用）。"""
    ins = [s.usage.get("input_tokens", 0) for s in traj.steps]
    monotonic = all(a < b for a, b in zip(ins, ins[1:]))
    peak = ins.index(max(ins)) if ins else -1
    return {"monotonic": monotonic, "peak": peak, "steps": len(ins)}


def result_bytes(traj: Trajectory) -> list[tuple[str, int]]:
    """ツール結果の文字数。**保存コストの支配要因**（S07 の続き）。"""
    return [(r.call_id, len(r.content if r.ok else (r.error or "")))
            for step in traj.steps for r in step.results]


def main() -> None:
    reset_data()
    traj = run_case("expense_report", "経費レポート作成")

    print("=== ステップ単位の内訳（TASK-expense_report）===")
    print("単価表 | ステップ | LLM | ツール | 所要(ms) | 割合")
    for units in (UNITS_A, UNITS_B):
        for row in step_rows(traj, units):
            print(f"{units.label} | {row['step']} | {row['llm']} | {row['tool']} | "
                  f"{row['ms']} | {row['share']:.1f}%")

    print("\n=== 種別ごとの合計（単価表を差し替えると1位が入れ替わる）===")
    print("単価表 | llm | tool | 合計 | 1位")
    for units in (UNITS_A, UNITS_B):
        t = kind_totals(traj, units)
        print(f"{t['label']} | {t['llm']}ms（{t['llm_share']:.1f}%） | "
              f"{t['tool']}ms（{t['tool_share']:.1f}%） | {t['total']}ms | {t['top']}")
    print("→ 「LLM が支配的」は単価表の性質であって、エージェントの性質ではない。"
          "内訳を出すときは単価表も一緒に記録する。")

    print("\n=== コストの形（近似トークン数＝プロンプトの文字数÷3・比較用）===")
    shape = token_shape(traj)
    print(f"ステップ数={shape['steps']} "
          f"入力トークンはステップごとに単調増加しているか: "
          f"{'はい' if shape['monotonic'] else 'いいえ'}")
    print(f"最も大きいステップ: step[{shape['peak']}]（最後のステップ）")
    print("→ 履歴が毎回全部送られるため、後のステップほど高い。"
          "実際の値は `python tools/traj_stats.py` で見られる（S03 の 13 → 129 → 374 → 545）。")

    print("\n=== 未計測を 0 と書かない ===")
    print(f"単価の出どころ: {UNITS_A.describe()}")
    print("llm と tool の単価は宣言値（実測ではない）。実測は隔離実行の 115 ms だけである"
          "（2026-08-15 実測 / 空のコード 63 ms / print 1行 115 ms / タイムアウト 2,090 ms）。")

    reset_data()


if __name__ == "__main__":
    main()
