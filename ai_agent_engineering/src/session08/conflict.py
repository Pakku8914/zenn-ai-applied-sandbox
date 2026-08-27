#!/usr/bin/env python3
"""セッション8：共有状態（ブラックボード）の競合。

競合はモデルの賢さと関係がない。**書き込みの設計**の問題である。
乱数は使わない。必ず競合する固定の枠（みなと 10:00 = `CONFLICT_SLOTS`）で起こすので、
何度実行しても同じ結果になる。

    python src/session08/conflict.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from agentkit.multi import Blackboard  # noqa: E402
from sideeffects import bookings_rows, reset_data  # noqa: E402

ROOM = "みなと"          # 10:00 の枠は必ず競合する（決定的に失敗させるため）
STRATEGIES = ("each", "same", "latest_only", "read_all")
LABELS = {
    "each": "2体がそれぞれ予約する",
    "same": "2体が同じ枠を取りにいく",
    "latest_only": "書くのは1体・latest() だけ見る",
    "read_all": "書くのは1体・read() で全候補を見る",
}


def book(tools, start: str, minutes: int = 60):
    """会議室を1件予約する（副作用あり・冪等でない）。"""
    return tools.call(ToolCall("bk", "book_room",
                              {"room": ROOM, "start": start, "minutes": minutes}))


def lost_update() -> dict:
    """同じ鍵に2体が書いたとき、`latest()` には最後の書き手しか出てこない。

    `Blackboard` は追記式なので値そのものは消えない（`read()` で全部見える）。
    `latest()` だけを見る設計が消しているのは値ではなく、**競合が起きた事実**である。
    """
    blackboard = Blackboard()
    blackboard.write("booker_a", "slot", f"{ROOM} 11:00")
    blackboard.write("booker_b", "slot", f"{ROOM} 14:00")
    return {"latest": blackboard.latest("slot"),
            "read": blackboard.read("slot"),
            "entries": len(blackboard.entries)}


def race(strategy: str) -> dict:
    """会議室を押さえる4通りのやり方。予約の回数はデータ側で数える。"""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy は {list(STRATEGIES)} のいずれかです: {strategy!r}")
    reset_data()
    blackboard = Blackboard()
    tools = build_registry().subset(["book_room"])
    tried = 0

    if strategy in ("each", "same"):
        plan = (("booker_a", "11:00"), ("booker_b", "14:00")) if strategy == "each" \
            else (("booker_a", "10:00"), ("booker_b", "10:00"))
        for author, start in plan:
            result = book(tools, start)
            tried += 1
            blackboard.write(author, "slot",
                             f"{ROOM} {start}" + ("" if result.ok else "（失敗）"))
    else:
        # 決めるのは2体、書くのは1体。候補の**並びの最後**が競合する枠になっている
        blackboard.write("booker_a", "slot", f"{ROOM} 11:00")
        blackboard.write("booker_b", "slot", f"{ROOM} 10:00")
        candidates = ([blackboard.latest("slot")] if strategy == "latest_only"
                      else blackboard.read("slot"))
        booked = None
        for value in candidates:
            result = book(tools, value.split()[-1])
            tried += 1
            if result.ok:
                booked = value.split()[-1]
                break
        blackboard.write("writer", "slot",
                         f"{ROOM} {booked}（確定）" if booked else f"{ROOM} 予約できず")

    return {"やり方": LABELS[strategy], "予約行数": bookings_rows(),
            "黒板の記録": len(blackboard.entries), "latest": blackboard.latest("slot"),
            "試した回数": tried}


def render(rows: list[dict]) -> str:
    lines = ["やり方 | 予約行数 | 黒板の記録 | latest が指す値 | 試した回数"]
    for r in rows:
        lines.append(f"{r['やり方']} | {r['予約行数']} | {r['黒板の記録']} | "
                     f"{r['latest']} | {r['試した回数']}")
    return "\n".join(lines)


def main() -> None:
    lost = lost_update()
    print(f"latest()={lost['latest']} / read()={lost['read']} / "
          f"記録={lost['entries']} 件")
    print()
    print(render([race(s) for s in STRATEGIES]))
    reset_data()


if __name__ == "__main__":
    main()
