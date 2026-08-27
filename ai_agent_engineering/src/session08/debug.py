#!/usr/bin/env python3
"""セッション8：複数体構成の切り分け（どこで落ちたかを機械的に特定する）。

1体なら「軌跡を上から読む」で足りた。複数体では軌跡が体の数だけに分かれ、
**境界（引き継ぎ）で落ちた情報**は、どの軌跡を見ても書かれていない。
分けた分だけ、境界を検査する道具が必要になる。

    python src/session08/debug.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runners import run_handoff, run_orchestrator  # noqa: E402
from sideeffects import reset_data  # noqa: E402

TRACE_DIR = ROOT / "traces" / "session08"

# 各役が仕事をするために必要な入力。
# 同じ組の中はどれか1つあればよい（件数だけ渡す形と一覧を渡す形の両方を許す）。
REQUIRED_INPUT = {
    "analyst": (("expenses",), ("threshold",)),
    "writer": (("by_category",), ("total",), ("violations",)),
    "notifier": (("report_path",), ("violations_count", "violations")),
}


def audit_hops(result: dict) -> list[dict]:
    """引き継ぎの記録を見て、受け取り手が必要とする入力が入っていたかを判定する。"""
    rows: list[dict] = []
    for hop in result["ledger"].hops:
        keys = set(hop["keys"])
        missing = ["/".join(group) for group in REQUIRED_INPUT.get(hop["to"], ())
                   if not (set(group) & keys)]
        rows.append({"区間": f"{hop['from']}→{hop['to']}", "項目数": hop["fields"],
                     "欠けた入力": missing})
    return rows


def first_loss(result: dict) -> str | None:
    """最初に情報が落ちた区間。ここより下流を直しても成果物は戻らない。"""
    for row in audit_hops(result):
        if row["欠けた入力"]:
            return row["区間"]
    return None


def render_audit(result: dict) -> str:
    lines = [f"方式={result['方式']} "
             f"採点={result['score']['passed']}/{result['score']['total']}",
             "区間 | 項目数 | 欠けた入力"]
    for row in audit_hops(result):
        lines.append(f"{row['区間']} | {row['項目数']} | "
                     f"{'（なし）' if not row['欠けた入力'] else ', '.join(row['欠けた入力'])}")
    lines.append(f"最初に落ちた区間: {first_loss(result) or '（落ちていない）'}")
    return "\n".join(lines)


def render_runs(result: dict) -> str:
    """どのワーカーの軌跡を読めばよいかを一覧にする。"""
    lines = [f"方式={result['方式']}"]
    for role, traj in result["trajectories"].items():
        lines.append(f"  {role} 手数={len(traj.steps)} stop={traj.stop_reason} "
                     f"tools={traj.tool_names}")
    return "\n".join(lines)


def save_traces(result: dict, name: str) -> list[Path]:
    """ワーカーごとに軌跡を保存する。1体1ファイルにしないと後から読めない。"""
    directory = TRACE_DIR / name
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for role, traj in result["trajectories"].items():
        path = directory / f"{role}.jsonl"
        traj.to_jsonl(path)
        paths.append(path)
    return paths


def main() -> None:
    for label, result in (("orchestrator_free", run_orchestrator("free")),
                          ("handoff_own", run_handoff("own")),
                          ("orchestrator_structured", run_orchestrator("structured"))):
        print(render_audit(result))
        print(render_runs(result))
        saved = save_traces(result, label)
        print(f"軌跡を {len(saved)} ファイルに保存しました: {saved[0].parent}")
        print()
    reset_data()


if __name__ == "__main__":
    main()
