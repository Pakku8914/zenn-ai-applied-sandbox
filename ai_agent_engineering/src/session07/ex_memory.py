#!/usr/bin/env python3
"""練習問題の解答コード（セッション7）。

  - 問題5: 要約しても制約は落とさない要約器
  - 問題6: 外部化した記録から必要な行だけ引き戻す
  - 問題8: 圧縮で制約が落ちたことを検出するガード

    python src/session07/ex_memory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compress  # noqa: E402

from longterm import AuditMemory  # noqa: E402
from records import body_of, kind_of, record  # noqa: E402
from runner import MemoryRunner, active_rules, build, judge  # noqa: E402

REQUIRED_RULES = ("amount", "deadline", "note")   # この監査で欠けてはいけない規則


# --- 問題5: 制約を残す要約器 ------------------------------------------------
def summarize_keep_constraints(group: list[str], key: str) -> list[str]:
    """かたまりを要約するが、中にあった制約はそのまま残す。

    元の `compress.summarize_group` との違いは最後の1行だけである。
    「要約してよいもの」と「要約してはいけないもの」を分けるのが要点。
    """
    refs = sum(1 for r in group if "起票" in body_of(r))
    return ([record("要約", f"{key} のログ {len(group)} 行を要約。"),
             record("要約", f"{key} 参照した申請は {refs} 件。")]
            + [r for r in group if kind_of(r) == "制約"])


def run_with_keep_summary() -> tuple[MemoryRunner, object]:
    """要約器を差し替えて走らせる（`compress` のモジュール変数を置き換える）。"""
    original = compress.summarize_group
    compress.summarize_group = summarize_keep_constraints
    try:
        runner = build("summarize")
        traj = runner.run()
    finally:
        compress.summarize_group = original      # 後片付けを忘れると他の検証に漏れる
    return runner, traj


# --- 問題6: 必要な行だけ引き戻す --------------------------------------------
def recall_into_memory(runner: MemoryRunner, query: str, limit: int = 3) -> list[str]:
    """外部化した記録から一致した行だけを短期メモリに戻す。"""
    if runner.longterm is None:
        return []
    lines = runner.longterm.recall_lines(query, limit=limit)
    for line in lines:
        runner.add_record(line)
    return lines


# --- 問題8: 圧縮による失敗を検出するガード ---------------------------------
def missing_rules(records: list[str], required=REQUIRED_RULES) -> list[str]:
    """判定に必要な規則がメモリから消えていないかを調べる。"""
    active = active_rules(records)
    return [name for name in required if name not in active]


def guard_report() -> dict:
    """方式ごとに「欠けた規則」と「指摘の件数」を並べる。"""
    out = {}
    for policy in ("truncate", "summarize", "keep", "externalize"):
        memory = AuditMemory(f"guard_{policy}")
        memory.clear()
        runner = build(policy, longterm=memory)
        traj = runner.run()
        out[policy] = {"欠けた規則": missing_rules(runner.memory.items),
                       "指摘": len(judge(runner.memory.items)),
                       "停止理由": traj.stop_reason}
    return out


if __name__ == "__main__":
    runner, traj = run_with_keep_summary()
    print("問題5: 制約を残す要約器")
    print(f"  {runner.result(traj)}")

    ext = AuditMemory("ex_externalize")
    ext.clear()
    ext_runner = build("externalize", longterm=ext)
    ext_traj = ext_runner.run()
    before = len(ext_runner.memory.items)
    lines = recall_into_memory(ext_runner, "EXP-0004")
    print("問題6: 必要な行だけ引き戻す")
    print(f"  引き戻した行={len(lines)} 記録={before} → {len(ext_runner.memory.items)}")
    for line in lines:
        print(f"  {body_of(line)}")

    print("問題8: 圧縮による失敗を検出するガード")
    for policy, row in guard_report().items():
        print(f"  {policy:<12} 欠けた規則={row['欠けた規則']} 指摘={row['指摘']}件")
