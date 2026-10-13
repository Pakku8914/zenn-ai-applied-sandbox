"""各セッションの verify*.py が使う小道具。期待値と違えば非0で終了する。

    from kondate.verifykit import check, eq, finish, sse_events

    @check("V1 ...")
    def _():
        eq(actual, expected, "何を比べたか")
        return "出力に添える短い説明（任意）"

    finish("session05")

async 関数にも @check を付けられる（中で asyncio.run する）。
出力は本文の「期待される出力」にそのまま転記するので、所要時間など実行ごとに変わる値は出さない。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import traceback
from collections.abc import Callable, Iterable

_results: list[tuple[str, bool]] = []


def check(name: str) -> Callable[[Callable[[], object]], None]:
    def run(fn: Callable[[], object]) -> None:
        try:
            note = asyncio.run(fn()) if inspect.iscoroutinefunction(fn) else fn()
            _results.append((name, True))
            print(f"PASS {name}{' — ' + str(note) if note else ''}", flush=True)
        except Exception:
            _results.append((name, False))
            print(f"FAIL {name}\n{traceback.format_exc()}", flush=True)
    return run


def eq(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def finish(label: str) -> None:
    failed = [n for n, ok in _results if not ok]
    print(f"== {label}: {len(_results) - len(failed)}/{len(_results)} passed", flush=True)
    sys.exit(1 if failed else 0)


def sse_events(lines: Iterable[str]) -> list[dict]:
    """SSE の行を {"event", "data", "id", "comments"} の辞書の列にする（data は JSON なら解析する）。"""
    events: list[dict] = []
    cur: dict = {"event": None, "data": [], "id": None, "comments": []}
    for line in lines:
        if line == "":
            if cur["data"] or cur["event"] or cur["comments"]:
                raw = "\n".join(cur["data"])
                try:
                    data = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    data = raw
                events.append({"event": cur["event"], "data": data, "id": cur["id"], "comments": cur["comments"]})
            cur = {"event": None, "data": [], "id": None, "comments": []}
            continue
        if line.startswith(":"):
            cur["comments"].append(line[1:].strip())
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            cur["data"].append(value)
        elif field in ("event", "id"):
            cur[field] = value
    return events
