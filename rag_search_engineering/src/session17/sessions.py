#!/usr/bin/env python3
"""セッション単位の分析（言い換え率）。

  python src/session17/sessions.py

corpus/query_log.jsonl（v1）には session_id が無いので、この指標は**計算できない**。
ここでは v2 スキーマで取り直したと仮定した小さなサンプル
（src/session17/sample/query_log_v2.jsonl・8行）で配管だけを作る。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SAMPLE_PATH = Path(__file__).resolve().parent / "sample" / "query_log_v2.jsonl"


def load_sample(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path is not None else SAMPLE_PATH
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_ts(row: dict) -> datetime:
    return datetime.fromisoformat(row["ts"])


def split_sessions(rows: list[dict], gap_min: int = 30) -> list[list[dict]]:
    """session_id でまとめ、gap_min 分より長い間隔が空いたら別セッションに割る。

    session_id はハッシュ化されていてもよい（同一性さえ保たれていれば足りる）。
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["session_id"], []).append(row)

    sessions: list[list[dict]] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda r: r["ts"])
        current = [ordered[0]]
        for prev, row in zip(ordered, ordered[1:]):
            gap = (parse_ts(row) - parse_ts(prev)).total_seconds() / 60.0
            if gap > gap_min:
                sessions.append(current)
                current = [row]
            else:
                current.append(row)
        sessions.append(current)
    return sessions


def reformulation_rate(rows: list[dict], gap_min: int = 30) -> float:
    """言い換え率＝「同一セッションで2件目以降に投げられたクエリ」の割合。

    利用者が1回で目的の文書に届かなかった回数の代理指標になる。
    """
    if not rows:
        raise ValueError("空のログには言い換え率がありません")
    sessions = split_sessions(rows, gap_min=gap_min)
    return (len(rows) - len(sessions)) / len(rows)


def zero_hit_followup(rows: list[dict], gap_min: int = 30) -> tuple[int, int]:
    """ゼロヒットのうち、同一セッションで言い換えが続いた件数 / ゼロヒット総数。"""
    followed = 0
    total = 0
    for session in split_sessions(rows, gap_min=gap_min):
        for i, row in enumerate(session):
            if row["n_results"] == 0:
                total += 1
                if i < len(session) - 1:
                    followed += 1
    return followed, total


def main() -> None:
    rows = load_sample()
    sessions = split_sessions(rows)
    print("=== v2 サンプル（8行）===")
    print(f"行数 : {len(rows)}")
    print(f"セッション数（30分で分割）: {len(sessions)}")
    print(f"言い換え率 : {reformulation_rate(rows):.3f}")
    followed, total = zero_hit_followup(rows)
    print(f"ゼロヒットのあと言い換えが続いた : {followed} / {total}")

    print("\n=== セッションの中身 ===")
    for session in sorted(sessions, key=lambda s: s[0]["ts"]):
        head = session[0]
        print(f"[{head['session_id']}] {head['ts']}")
        for row in session:
            mark = "ゼロヒット" if row["n_results"] == 0 else f"{row['n_results']}件"
            click = "クリック有" if row["clicked_rank"] else "クリック無"
            print(f"  - {row['query_text']} / {mark} / {click}")


if __name__ == "__main__":
    main()
