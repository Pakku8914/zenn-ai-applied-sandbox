#!/usr/bin/env python3
"""復習03：壊れたときにどこへ出るか（S04 × S11）。

「壊れない形」を設計するとは、壊れないようにすることではない。
**壊れたときの出口を決めておく**ことである。ここでは出口を3つに絞る。

  続ける   … 失敗したツール結果としてモデルに返し、別の手を打たせる
  人に渡す … 引き継ぎ書を返して止まる（stop_reason=error）
  増やさない … 副作用を2件に増やさない（冪等性の担保）

    python src/review03/failure_map.py

**副作用を出す測定を含む。** 各測定の前後で `tools/make_data.py` を実行して
業務データを初期状態に戻す（経費6件）。戻す処理を消さないこと。

`agentkit` と `src/session11/` は1行も変更しない。
"""

from __future__ import annotations

from _paths import reset_data, setup

ROOT = setup()

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from failure_kinds import (ACTION_JA, KIND_JA, classify_error,  # noqa: E402
                           has_alternative, retry_decision)
from faults import AFTER_MESSAGE, BEFORE_MESSAGE  # noqa: E402
from idempotency import (build_registry_with_flaky_submit,  # noqa: E402
                         build_submit_registry, count_rows, expense_key)
from retry_runner import ReliableRunner, retry_blindly, retry_guarded  # noqa: E402
from retry_scenarios import EXPENSE_SUBMIT, TASK_SUBMIT  # noqa: E402

SUBMIT_ARGS = {"employee": "高橋 涼", "amount": 68_000, "category": "接待交際費",
               "note": "取引先との打ち合わせ",
               "idempotency_key": expense_key("EMP-003", 68_000)}
SUBMIT_CALL = ToolCall("r3-submit", "submit_expense", SUBMIT_ARGS)


def conflict_message() -> str:
    """競合エラーの文面を実装から取る（本文に書き写さない）。予約は作られない。"""
    result = build_registry().call(
        ToolCall("r3-book", "book_room", {"room": "みなと", "start": "10:00"}))
    return result.error or ""


def cases() -> list[tuple[str, str, bool]]:
    """（ケース名, エラーメッセージ, そのツールは冪等か）。

    同じメッセージを冪等・非冪等の2通りで並べるのが要点である。
    **メッセージだけでは判断が決まらない**ことが表から読み取れる。
    """
    return [
        ("応答が返らない（冪等でない実装）", AFTER_MESSAGE, False),
        ("応答が返らない（冪等な実装）", AFTER_MESSAGE, True),
        ("接続できない（冪等でない実装）", BEFORE_MESSAGE, False),
        ("接続できない（冪等な実装）", BEFORE_MESSAGE, True),
        ("会議室の枠が埋まっている", conflict_message(), False),
        ("内部エラー", "内部エラー（ZeroDivisionError）", True),
    ]


def decisions(max_retries: int = 1) -> list[dict]:
    """1回の失敗に対する判断を、決定的に並べる。"""
    rows = []
    for label, message, idempotent in cases():
        decision = retry_decision(message, idempotent=idempotent, attempts=1,
                                  max_retries=max_retries)
        rows.append({"ケース": label, "種類": KIND_JA[classify_error(message)],
                     "代替案": "あり" if has_alternative(message) else "なし",
                     "冪等": "はい" if idempotent else "いいえ",
                     "判断": ACTION_JA[decision.action]})
    return rows


# ---------------------------------------------------------------------------
# 副作用の回数は軌跡ではなくデータ側で数える（S06 以降の規約）
# ---------------------------------------------------------------------------
def side_effects() -> list[dict]:
    """再試行のやり方を3通り変えて、expenses の増分を数える。"""
    variants = (
        ("無条件に1回再試行（レビュー前の設定）", False, retry_blindly, "二重申請になる"),
        ("判断つきの再試行（冪等でない実装）", False, retry_guarded, "再試行せず人に渡す"),
        ("判断つきの再試行（冪等キー付きの実装）", True, retry_guarded, "重複を吸収して1件のまま"),
    )
    rows = []
    for label, idempotent, how, note in variants:
        reset_data()
        before = count_rows("expenses")
        registry = build_submit_registry(idempotent=idempotent, fail_on=(1,), when="after")
        result, attempts, waited = how(registry, SUBMIT_CALL, max_retries=1)
        rows.append({"やり方": label, "増分": count_rows("expenses") - before,
                     "試行": attempts, "待機": waited,
                     "成功": "はい" if result.ok else "いいえ", "備考": note})
    reset_data()
    return rows


def completion_check() -> dict:
    """モデルの「登録しました」を完了判定に使わない（F8 の確かめ方）。"""
    reset_data()
    before = count_rows("expenses")
    registry = build_registry_with_flaky_submit(idempotent=False, fail_on=(1,),
                                                when="after")
    traj = ReliableRunner(ScriptedClient(EXPENSE_SUBMIT), registry, max_retries=1,
                          task_id="TASK-R03-DONE").run(TASK_SUBMIT)
    claim = EXPENSE_SUBMIT["turns"][-1]["final"]
    final = traj.final or ""
    row = {"stop_reason": traj.stop_reason, "ステップ": len(traj.steps),
           "増分": count_rows("expenses") - before,
           "モデルの申告": claim,
           "そのまま返したか": final == claim,
           "分からない操作を挙げたか": "実行されたか分からない操作" in final}
    reset_data()
    return row


# ---------------------------------------------------------------------------
# 失敗の出口の図（問題6でここを自分で書く）
# ---------------------------------------------------------------------------
def render_mermaid() -> str:
    """失敗の分類から出口までを1枚にする。図にできない設計は運用できない。"""
    return "\n".join([
        "flowchart TD",
        '  F["ツールが失敗した"] --> K{"失敗の種類"}',
        '  K -->|部分的| I{"冪等か"}',
        '  K -->|一時的| I',
        '  K -->|恒久的・代替案あり| A["引数を変えて再試行"]',
        '  K -->|恒久的・代替案なし| S["再試行しない"]',
        '  K -->|不明| H["人に渡す"]',
        '  I -->|はい| R["同じ引数で再試行"]',
        '  I -->|いいえ| H',
        '  A --> C["失敗したツール結果としてモデルに返す"]',
        '  S --> C',
        '  R --> C',
        '  H --> O["引き継ぎ書を返す（stop_reason=error）"]',
    ])


def render() -> str:
    lines = [f"=== 失敗の出口（{len(cases())} ケース）===",
             "ケース | 種類 | 代替案 | 冪等 | 判断"]
    for row in decisions():
        lines.append(f"{row['ケース']} | {row['種類']} | {row['代替案']} | "
                     f"{row['冪等']} | {row['判断']}")
    lines += ["", "=== 二重申請は起きるか（expenses の増分で数える）===",
              "やり方 | 増分 | 試行 | 待機 | 成功 | 備考"]
    for row in side_effects():
        lines.append(f"{row['やり方']} | {row['増分']} | {row['試行']} | "
                     f"{row['待機']} | {row['成功']} | {row['備考']}")
    done = completion_check()
    lines += ["", "=== モデルの申告を完了判定に使わない ===",
              f"stop_reason={done['stop_reason']} / ステップ={done['ステップ']} / "
              f"expenses の増分={done['増分']} 行",
              f"モデルの申告: {done['モデルの申告']}",
              f"それをそのまま返したか: {'はい' if done['そのまま返したか'] else 'いいえ'}",
              f"実行されたか分からない操作を挙げたか: "
              f"{'はい' if done['分からない操作を挙げたか'] else 'いいえ'}",
              "", "=== 失敗の出口（図）===", render_mermaid()]
    return "\n".join(lines)


def main() -> None:
    print(render())


if __name__ == "__main__":
    main()
