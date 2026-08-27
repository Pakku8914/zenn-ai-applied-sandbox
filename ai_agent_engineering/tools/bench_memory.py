#!/usr/bin/env python3
"""メモリの実測 — 溢れる過程・内訳・圧縮方式の比較（すべて決定的）。

    python tools/bench_memory.py

本文（セッション7）に書いた数値の出典。トークン数は**近似トークン数（比較用）**で、
1記録 = 33文字 = 11トークン相当として数える（実 API の課金額ではない）。
数値が変わる変更をしたときは、この出力に合わせて本文を直すこと。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "src" / "session07")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.memory import extract_constraints  # noqa: E402
from compress import POLICY_LABELS, apply_policy  # noqa: E402
from longterm import AuditMemory, recall_modes  # noqa: E402
from records import (body_of, breakdown, constraints, retention,  # noqa: E402
                     tokens)
from runner import MAX_CONTEXT, build, judge  # noqa: E402

POLICIES = ("none", "truncate", "summarize", "keep", "externalize", "summarize_all")


def run(policy: str):
    memory = AuditMemory(f"bench_{policy}")
    memory.clear()
    runner = build(policy, longterm=memory)
    return runner, runner.run()


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    # --- 1. 溢れる過程 -----------------------------------------------------
    naive, traj = run("none")
    section(f"1. 溢れる過程（圧縮なし / 上限 近似{MAX_CONTEXT}トークン）")
    print("step 記録 近似トークン 増えた記録 ツール")
    for s in traj.steps:
        u = s.usage
        names = ", ".join(c.name for c in s.calls) or "（ツールなし）"
        print(f"{s.index:>4} {u['records']:>4} {u['memory_tokens']:>12} "
              f"{u['added']:>10} {names}")
    print(f"停止理由={traj.stop_reason} 手数={len(traj.steps)}")
    print(f"final: {traj.final}")

    # --- 2. 何が支配的か ---------------------------------------------------
    section("2. 溢れた瞬間の内訳")
    items = naive.memory.items
    print(f"記録数={len(items)} 近似トークン={tokens(items)}")
    for row in breakdown(items):
        print(f"{row['要素']:<10} 記録={row['記録数']:>4} "
              f"近似={row['近似トークン']:>5} 割合={row['割合']:>5}%")
    logs = [r for r in items if r.startswith("[ログ]") or r.startswith("[制約] 0")]
    print(f"うち監査ログ由来={len(logs)} 割合="
          f"{round(len(logs) / len(items) * 100, 1)}%")

    # --- 3. 圧縮方式の比較（溢れた瞬間に1回だけ適用する）------------------
    section("3. 溢れた瞬間に適用したときの比較")
    print("方式 記録 近似トークン 制約 落ちた制約")
    for policy in ("truncate", "summarize", "keep", "summarize_all"):
        after = apply_policy(policy, naive.memory)
        info = retention(items, after.items)
        print(f"{POLICY_LABELS[policy]:<16} {len(after.items):>4} "
              f"{after.total_tokens():>6} "
              f"{info['残った制約']}/{info['制約の総数']} "
              f"{len(info['落ちた制約'])}件")

    # --- 4. 最後まで走らせたときの成果 -------------------------------------
    section("4. 完走したときの成果（同じタスク・同じシナリオ）")
    print("方式 手数 最終記録 近似トークン 制約 指摘 停止理由 圧縮回数")
    for policy in POLICIES:
        runner, t = run(policy)
        row = runner.result(t)
        print(f"{row['方式']:<16} {row['手数']:>3} {row['最終記録数']:>5} "
              f"{row['近似トークン']:>6} {row['制約']:>5} {row['指摘']:>3}件 "
              f"{row['停止理由']:<8} {row['圧縮回数']}")

    # --- 5. 何が落ちたのか -------------------------------------------------
    section("5. 切り捨てで落ちた制約")
    trunc, t = run("truncate")
    for body in trunc.lost_constraints:
        print(f"  落ちた: {body}")
    for rec in constraints(trunc.memory.items):
        print(f"  残った: {body_of(rec)}")
    print(f"  指摘={len(judge(trunc.memory.items))}件"
          f"（本来は{len(judge(run('keep')[0].memory.items))}件）")

    # --- 6. 制約の見つけ方 -------------------------------------------------
    section("6. 制約の見つけ方（種別タグ と 正規表現）")
    keep_runner, _ = run("keep")
    tagged = constraints(keep_runner.first_seen)
    seen: list[str] = []
    for rec in tagged:
        if rec not in seen:
            seen.append(rec)
    hits = [r for r in seen if extract_constraints(r)]
    print(f"種別タグ={len(seen)}件 正規表現={len(hits)}件 "
          f"取りこぼし={len(seen) - len(hits)}件")
    for rec in seen:
        if rec not in hits:
            print(f"  取りこぼし: {body_of(rec)}")

    # --- 7. いつ引くか -----------------------------------------------------
    section("7. いつ長期メモリを引くか")
    print("方式 引いた回数 予約の試行 失敗 押さえた枠")
    for row in recall_modes():
        print(f"{row['方式']:<12} {row['引いた回数']:>4} {row['予約の試行']:>4} "
              f"{row['失敗']:>3} {row['押さえた枠']}")


if __name__ == "__main__":
    main()
