#!/usr/bin/env python3
"""ワークフロー版とエージェント版を、同じ業務要求で並べて比べる。

見るのは3つだけ。
  - LLM を何回呼んだか（＝手数。エージェントは1ステップ1回）
  - ツールを何回呼んだか（＝実際に業務に触った回数）
  - 近似トークン量（履歴が毎回全部送られるので、手数より速く増える）

近似トークンは決定的な近似値（プロンプトの文字数 ÷ 3）である。実 API の課金額とは
一致しないので、絶対値ではなく**条件を変えたときの比較**に使う。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agent_book_room as agent_side  # noqa: E402
import workflow_book_room as workflow_side  # noqa: E402


def main() -> None:
    # --- 表1: 経路が固定できる仕事 -----------------------------------------
    wf = workflow_side.book_with_fallback("みなと", ["10:00", "11:00"])
    traj = agent_side.run_conflict_retry()
    tok = traj.total_tokens

    print("=== 表1: 経路が固定できる仕事（みなと 10:00 が競合する）===")
    print("方式 | LLM 呼び出し | ツール呼び出し | 近似 in | 近似 out | 結果")
    print(f"ワークフロー（候補を列挙） | {wf.llm_calls} | {len(wf.tool_calls)} | 0 | 0 | "
          f"{'成功' if wf.ok else '失敗'}")
    print(f"エージェント | {len(traj.steps)} | {len(traj.tool_names)} | "
          f"{tok['input']} | {tok['output']} | "
          f"{'成功' if traj.stop_reason == 'done' else traj.stop_reason}")
    print(f"ワークフローの結果: {wf.message}")
    print(f"エージェントの結果: {traj.final}")

    # --- 表2: 経路が固定できない仕事 ---------------------------------------
    naive = workflow_side.book_fixed("大会議室", "13:00")
    cap = agent_side.run_capacity()

    print("\n=== 表2: 経路が固定できない仕事（13:00 に定員10名以上を確保する）===")
    print("方式 | LLM 呼び出し | ツール呼び出し | 結果")
    print(f"ワークフロー（大会議室 13:00 に固定） | {naive.llm_calls} | "
          f"{len(naive.tool_calls)} | {'成功' if naive.ok else '失敗（行き止まり）'}")
    print(f"エージェント | {len(cap.steps)} | {len(cap.tool_names)} | "
          f"{'成功' if cap.stop_reason == 'done' else cap.stop_reason}")
    print(f"ワークフローの結果: {naive.message}")
    print(f"エージェントの結果: {cap.final}")

    print("\n※ 表1のエージェント行は tools/traj_stats.py の「会議室予約（競合あり）」と同じ条件です。")
    print("※ 近似トークンは文字数÷3の決定的な近似値です。比較にだけ使ってください。")


if __name__ == "__main__":
    main()
