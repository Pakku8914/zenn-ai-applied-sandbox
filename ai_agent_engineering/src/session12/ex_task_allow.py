#!/usr/bin/env python3
"""練習問題4の参照解：タスクごとの許可リストを比べる。

最小権限は「要らないものを外す」層であって、「要るものを止める」層ではない。
同じ攻撃を、外に出る出口を持たないタスクと、業務上どうしても持つタスクで測ると、
その違いが数値に出る。

    python src/session12/ex_task_allow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import layers  # noqa: E402
from layers import COLUMNS, Config, render, reset, run_config  # noqa: E402

# タスクA：調べて要点をまとめるだけ（外へ出る出口が1つも無い）
TASK_A = ["search_docs", "get_policy"]
# タスクB：下書きを作り、担当者へ共有する（本文の TASK_ALLOW と同じ）
TASK_B = ["search_docs", "get_policy", "write_file", "send_message"]


def with_allow(label: str, names: list[str]) -> dict:
    """許可リストを差し替えて測る。

    `layers.build_tools()` は自モジュールの `TASK_ALLOW` を参照するので、
    そこを一時的に差し替える。測定でグローバルを触るときは必ず `finally` で戻す。
    """
    original = layers.TASK_ALLOW
    layers.TASK_ALLOW = names
    try:
        return run_config(Config(label, privilege=True))
    finally:
        layers.TASK_ALLOW = original


def main() -> None:
    rows = [with_allow("タスクA（2ツール）", TASK_A),
            with_allow("タスクB（4ツール）", TASK_B)]
    print(render(rows, COLUMNS))
    reset()


if __name__ == "__main__":
    main()
