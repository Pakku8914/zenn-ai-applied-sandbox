#!/usr/bin/env python3
"""セッション4の実測（すべて決定的）。本文の数値はこのスクリプトの出力。

    python src/session04/measure.py

近似トークン数は「文字数 ÷ 3」の比較用の値であり、実 API の課金額ではない。
各セクションは実行前に `tools/make_data.py` でデータを初期状態へ戻すので、
何度実行しても同じ数値になる。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agentkit.biztools import DATA, list_expenses, submit_expense  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from badtools import build_bad_registry, dump_expenses  # noqa: E402
from goodtools import (build_checked_registry, build_good_registry,  # noqa: E402
                      build_unchecked_registry, find_expenses, read_only,
                      render_tool_spec, submit_expense_once)

IDEM_KEY = "2026-08-15-EMP-003-68000"

# 不正な引数を3件。それぞれ違う種類の誤りにしてある
INVALID_ARGS = [
    {"employee": "高橋 涼", "amount": 68000, "category": "打ち上げ",
     "idempotency_key": "K1"},                                        # 区分が列挙外
    {"employee": "高橋 涼", "category": "接待交際費",
     "idempotency_key": "K2"},                                        # 必須の amount が無い
    {"employee": "高橋 涼", "amount": -3000, "category": "接待交際費",
     "idempotency_key": "K3"},                                        # 金額が負
]

# 悪い道具を渡されたモデルの応答（言い方を変えながら同じツールを4回呼ぶ）
BAD_SCENARIO = {
    "name": "bad_free_text",
    "turns": [
        {"thought": "経費の申請を頼まれた。まとめて処理できるツールがあるので使う。",
         "calls": [{"name": "manage_expense",
                    "args": {"instruction": "高橋 涼 の接待交際費 68000 円を申請して"}}]},
        {"thought": "失敗した。言い方を変えてみる。",
         "calls": [{"name": "manage_expense",
                    "args": {"instruction": "接待交際費 68000 円 高橋 涼"}}]},
        {"thought": "まだ失敗する。命令の形にしてみる。",
         "calls": [{"name": "manage_expense",
                    "args": {"instruction": "申請 高橋 涼 68000 接待交際費"}}]},
        {"thought": "空白の入れ方が悪いのかもしれない。",
         "calls": [{"name": "manage_expense",
                    "args": {"instruction": "申請 高橋涼 68000円 接待交際費"}}]},
    ],
}

# 良い道具を渡されたモデルの応答（1回失敗するが、エラーを読んで直せる）
GOOD_SCENARIO = {
    "name": "good_schema",
    "turns": [
        {"thought": "経費を申請する。区分は「打ち上げ」でよいはずだ。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68000,
                             "category": "打ち上げ", "idempotency_key": IDEM_KEY}}]},
        {"thought": "許容される区分が返ってきた。「接待交際費」で出し直す。",
         "calls": [{"name": "submit_expense",
                    "args": {"employee": "高橋 涼", "amount": 68000,
                             "category": "接待交際費", "idempotency_key": IDEM_KEY}}]},
        {"thought": "受け付けられたので報告する。",
         "final": "EXP-0007 として 68,000 円の接待交際費を申請しました。5万円以上なので承認が必要です。"},
    ],
}


def approx(text: str) -> int:
    """近似トークン数（比較用）＝文字数 ÷ 3。"""
    return len(text) // 3


def reset_data() -> None:
    """業務データを初期状態に戻す（決定的なので何度でも呼べる）。"""
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def row_count(name: str = "expenses") -> int:
    path = DATA / f"{name}.jsonl"
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


# ---------------------------------------------------------------------------
def section1() -> list[tuple[str, str]]:
    """同じ問いに対する4つの返し方。"""
    reset_data()
    return [
        ("dump_expenses()（全件・全項目の JSON）", dump_expenses()),
        ('list_expenses("all")（全件・6列のテーブル）', list_expenses("all")),
        ('list_expenses("submitted")（状態で絞る・6列）', list_expenses("submitted")),
        ('find_expenses("submitted", 50000)（状態と金額で絞る・5列・件数つき）',
         find_expenses("submitted", 50000)),
    ]


def section2() -> dict:
    """スキーマは同じ。検証するかしないかだけを変える。"""
    out: dict = {}
    for label, factory in (("検証なし", build_unchecked_registry),
                           ("検証あり", build_checked_registry)):
        reset_data()
        before = row_count()
        reg = factory()
        results = [reg.call(ToolCall(f"c{i}", "submit_expense", dict(args)))
                   for i, args in enumerate(INVALID_ARGS)]
        out[label] = {"results": results,
                      "reached": sum(1 for r in results if r.ok),
                      "added": row_count() - before}
    reset_data()
    return out


def section3() -> dict:
    """同じ申請を2回送る（再送は現場で必ず起きる）。"""
    out: dict = {}
    for label, fn in (("submit_expense（agentkit の既定）", submit_expense),
                      ("submit_expense_once（冪等キーで吸収）", submit_expense_once)):
        reset_data()
        before = row_count()
        ids = []
        for _ in range(2):
            msg = fn("高橋 涼", 68000, "接待交際費",
                     idempotency_key=IDEM_KEY, note="9月商談の会食")
            found = re.search(r"EXP-\d{4}", msg)
            ids.append(found.group() if found else "?")
        out[label] = {"ids": ids, "added": row_count() - before}
    reset_data()
    return out


def section4() -> dict:
    """読み取り専用の許可リストで書き込みを試す。"""
    reset_data()
    reg = read_only(build_good_registry())
    before = row_count()
    res = reg.call(ToolCall("c1", "submit_expense",
                            {"employee": "高橋 涼", "amount": 68000,
                             "category": "接待交際費", "idempotency_key": IDEM_KEY}))
    out = {"names": reg.names(), "ok": res.ok,
           "message": res.error or res.content, "added": row_count() - before}
    reset_data()
    return out


def run_trajectory(scenario: dict, registry, max_steps: int = 4):
    reset_data()
    agent = ReActAgent(ScriptedClient(scenario), registry, max_steps=max_steps)
    return agent.run("高橋 涼 の接待交際費 68,000 円を申請してください", task_id="TASK-004")


def section5() -> dict:
    """モデルの応答は固定。道具だけを差し替えて軌跡を比べる。"""
    pairs = [
        ("悪い道具（自由文字列1引数・エラーは「処理できませんでした。」）",
         run_trajectory(BAD_SCENARIO, build_bad_registry())),
        ("良い道具（スキーマ検証・許容値を返すエラー）",
         run_trajectory(GOOD_SCENARIO, build_good_registry())),
    ]
    reset_data()
    out: dict = {}
    for label, traj in pairs:
        out[label] = {
            "steps": len(traj.steps),
            "calls": len(traj.tool_names),
            "ok_calls": sum(1 for s in traj.steps for r in s.results if r.ok),
            "stop_reason": traj.stop_reason,
        }
    return out


def section6() -> str:
    """レジストリからツール仕様書を生成する。"""
    return render_tool_spec(build_good_registry())


# ---------------------------------------------------------------------------
def main() -> None:
    print("==============================================")
    print(" セッション4：ツール設計の実測（すべて決定的）")
    print("==============================================")

    print()
    print("=== 1. 同じ問いに対する4つの返し方 ===")
    print("問い: 5万円以上で未承認（submitted）の経費申請を知りたい")
    for label, text in section1():
        print(f"- {label}: {len(text)} 文字 / 近似 {approx(text)} トークン")

    print()
    print("=== 2. スキーマは宣言。検証しなければ守られない ===")
    print("不正な引数を3件送る（区分が列挙外 / 必須の amount が無い / 金額が負）")
    s2 = section2()
    for label in ("検証なし", "検証あり"):
        d = s2[label]
        print(f"- {label}のレジストリ: 副作用に到達 {d['reached']} 件 / "
              f"expenses.jsonl に増えた行 {d['added']} 行")
    for label in ("検証なし", "検証あり"):
        for i, res in enumerate(s2[label]["results"], start=1):
            msg = res.content if res.ok else (res.error or "")
            print(f"- {label}({i}) ok={str(res.ok):5s}: {msg}")

    print()
    print("=== 3. 冪等性（同じ申請を2回送る）===")
    for label, d in section3().items():
        print(f"- {label}: 2 回呼んで {d['added']} 行増えた"
              f"（{d['ids'][0]} / {d['ids'][1]}）")

    print()
    print("=== 4. 読み取りと書き込みを分ける ===")
    s4 = section4()
    print(f"- 読み取り専用レジストリのツール: {', '.join(s4['names'])}")
    print(f"- submit_expense を呼ぶ: ok={s4['ok']} / 増えた行 {s4['added']} 行")
    print(f"- 返ってきたメッセージ: {s4['message']}")

    print()
    print("=== 5. 軌跡（モデルの応答は固定。道具だけを差し替える）===")
    for label, d in section5().items():
        print(f"- {label}: 手数 {d['steps']} / 呼び出し {d['calls']} / "
              f"成功 {d['ok_calls']} / 停止理由 {d['stop_reason']}")

    print()
    print("=== 6. レジストリから生成したツール仕様書 ===")
    print(section6())

    reset_data()


if __name__ == "__main__":
    main()
