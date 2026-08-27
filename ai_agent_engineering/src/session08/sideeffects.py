#!/usr/bin/env python3
"""セッション8：副作用の観測とリセット。

軌跡（trajectory）を見ても副作用の回数は分からない。**送った・書いた回数は
データ側で数える**（セッション6で確立した規約）。複数体にすると「誰が書いたか」
まで分からなくなるので、この章では特に重要になる。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import DATA, WORKSPACE  # noqa: E402

REPORT_PATH = WORKSPACE / "session08" / "report.md"


def reset_data() -> None:
    """業務データと前回の成果物を初期状態に戻す。

    方式を比べるときは、前の方式が残したレポートや通知を持ち込んではいけない
    （前の実行の成果物を採点してしまい、比較が壊れる）。
    """
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""


def _rows(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def read_messages() -> list[dict]:
    """実際に送信されたメッセージ。承認ゲートはまだ無い（セッション10で足す）。"""
    return _rows("messages")


def bookings_rows() -> int:
    """実際に入った予約の件数。二重予約はここでしか見えない。"""
    return len(_rows("bookings"))


if __name__ == "__main__":
    reset_data()
    print(f"messages={len(read_messages())} bookings={bookings_rows()} "
          f"report={'あり' if read_report() else 'なし'}")
