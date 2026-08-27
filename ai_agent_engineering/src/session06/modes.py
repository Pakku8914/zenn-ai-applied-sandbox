#!/usr/bin/env python3
"""状態の持ち方3方式の比較と、アンチパターンの実演（すべて決定的）。

  方式1 履歴のみ        … 会話履歴だけを状態にする
  方式2 構造体＋履歴    … 状態を型で持つが、順序は守られない
  方式3 状態機械        … 許された遷移しか起こらない

    python src/session06/modes.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from runner import ResumableRunner, build_messages  # noqa: E402
from scenarios import RESEARCH  # noqa: E402
from states import TaskState, build_machine  # noqa: E402

TASK = ("経費精算の規程を確認し、規程に照らして問題のある申請を洗い出して"
        "レポートにまとめ、報告会の会議室を予約してください")
DIR = ROOT / "traces" / "checkpoints" / "session06_modes"

# モデルが進捗をプロンプトに書き足していくときの文面。3つ目だけ言い方が違う
PROGRESS_NOTES = ("G1 完了", "G2 完了", "G3は完了しました")


def reset_data() -> None:
    """業務データを初期状態に戻す（決定的なので何度でも呼べる）。"""
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


# ---------------------------------------------------------------------------
# 方式1：履歴のみ
# ---------------------------------------------------------------------------
def guess_state_from_history(messages: list[dict]) -> str:
    """履歴の文字列一致で「どこまで進んだか」を推測する（方式1の実装）。

    履歴には「実際に呼んだツール名」と「これから呼ぶつもりのツール名」が
    同じ文字列として並んでいる。両者を区別する手がかりは無い。
    """
    text = json.dumps(messages, ensure_ascii=False)
    if "book_room" in text:
        return "booking"
    if "write_file" in text:
        return "drafting"
    if "list_expenses" in text or "get_policy" in text:
        return "collecting"
    return "planning"


def history_only() -> dict:
    """2手だけ進めた時点で、履歴からの推測と実際の状態を比べる。"""
    reset_data()
    runner = ResumableRunner(ScriptedClient(RESEARCH), build_registry(),
                             task_id="TASK-006M", max_steps=2, checkpoint_dir=DIR)
    traj = runner.run(TASK)
    messages = build_messages(TASK, traj, None)  # view を渡さない＝履歴だけ
    return {"推測した状態": guess_state_from_history(messages),
            "実際の状態": runner.state.state,
            "履歴のメッセージ数": len(messages)}


# ---------------------------------------------------------------------------
# 方式2：構造体＋履歴（状態は読めるが、順序は守られない）
# ---------------------------------------------------------------------------
def struct_only() -> dict:
    st = TaskState(task_id="TASK-006M", state="collecting")
    st.state = "done"  # レポートも予約もしていないのに、誰も止めない
    consistent = st.report_path is not None and st.booking is not None
    return {"書き換え後の状態": st.state, "例外は出たか": False,
            "データと整合しているか": consistent}


# ---------------------------------------------------------------------------
# 方式3：状態機械（許された遷移しか起こらない）
# ---------------------------------------------------------------------------
def machine_guard() -> dict:
    machine = build_machine("collecting")
    try:
        machine.fire("booked")
    except ValueError as exc:
        return {"止まったか": True, "メッセージ": str(exc), "状態": machine.state}
    return {"止まったか": False, "メッセージ": "", "状態": machine.state}


# ---------------------------------------------------------------------------
# アンチパターン：状態をプロンプトの文字列として持つ
# ---------------------------------------------------------------------------
def prompt_state_antipattern() -> dict:
    prompt = "あなたはみなと商事の調査担当です。"
    lengths = [len(prompt)]
    for note in PROGRESS_NOTES:
        prompt = prompt + "\n進捗: " + note  # 積み上げる（消せない・上書きできない）
        lengths.append(len(prompt))
    read_back = re.findall(r"進捗: (G\d) 完了", prompt)
    return {"書き込んだ進捗": list(PROGRESS_NOTES), "読み戻せた進捗": read_back,
            "プロンプトの長さの推移": lengths}


def state_view_shape() -> dict:
    """良い側：状態の投影は毎回作り直す。鍵の集合は変わらない。"""
    a = TaskState(task_id="TASK-006M", state="collecting").prompt_view()
    b = TaskState(task_id="TASK-006M", state="booking",
                  violations=["EXP-0002"]).prompt_view()
    return {"鍵は同じか": sorted(a) == sorted(b), "鍵": sorted(a)}


def main() -> None:
    print("--- 方式1：履歴のみ ---")
    print(history_only())
    print("--- 方式2：構造体＋履歴 ---")
    print(struct_only())
    print("--- 方式3：状態機械 ---")
    print(machine_guard())
    print("--- アンチパターン：状態をプロンプトの文字列で持つ ---")
    print(prompt_state_antipattern())
    print("--- 良い側：状態の投影（view） ---")
    print(state_view_shape())
    reset_data()


if __name__ == "__main__":
    main()
