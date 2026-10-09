"""後半・練習問題1の解答：自前の SSE（API契約③）の決まりを1か所で検査する。"""

from __future__ import annotations

import json
import re

from ..testkit import TERMINAL, SseRun

ESCAPED = re.compile(r"\\u[0-9a-fA-F]{4}")  # JSON の中の「バックスラッシュ u と16進4桁」


def contract_violations(names: list[str], data_lines: list[str]) -> list[str]:
    """守れていない決まりを、見つけた順に日本語で返す（空なら合格）。"""
    problems: list[str] = []
    if not names or names[0] != "start":
        problems.append("最初のイベントが start ではない")
    ends = [i for i, n in enumerate(names) if n in TERMINAL]
    if len(ends) != 1 or ends[0] != len(names) - 1:
        problems.append("終端（done か error）が最後にちょうど1つではない")
    if names and names[-1] == "done" and (len(names) < 2 or names[-2] != "usage"):
        problems.append("done の直前が usage ではない")
    if names and names[-1] == "error" and "usage" in names:
        problems.append("error で終えたのに usage を送っている")
    for line in data_lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            problems.append("data が1行の JSON ではない")
            break
    if any(ESCAPED.search(line) for line in data_lines):
        problems.append("日本語がエスケープされている")
    return problems


def assert_sse_contract(run: SseRun) -> None:
    problems = contract_violations(run.names(), run.data_lines)
    assert not problems, "、".join(problems)
