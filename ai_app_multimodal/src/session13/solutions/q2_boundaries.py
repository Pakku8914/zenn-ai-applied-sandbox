"""問題2：保持期限の境界（1秒前は見える・ちょうどで見えない）を、種別ごとに FixedClock で確かめる。

    docker compose exec api python -m src.session13.solutions.q2_boundaries
"""

from __future__ import annotations

from datetime import timedelta

from kondate.clock import FixedClock
from src.session13.privacy import RETENTION, PersonalStore


def label(td: timedelta) -> str:
    hours = int(td.total_seconds()) // 3600
    return f"{hours}時間" if hours < 48 else f"{td.days}日"  # 2日未満は時間で表す


def visible(flag: bool) -> str:
    return "見える" if flag else "見えない"


def boundary(kind: str) -> tuple[bool, bool, int]:
    """(1秒前に見えるか, ちょうどで見えるか, ちょうどで掃除した件数)。"""
    clock = FixedClock()
    store = PersonalStore(clock)
    store.add(kind, "item_1", "u001")
    clock.advance(RETENTION[kind].total_seconds() - 1)
    before = store.get("u001", "item_1") is not None
    clock.advance(1)
    at = store.get("u001", "item_1") is not None
    return before, at, sum(store.sweep().values())


def report() -> list[str]:
    lines = []
    for kind, td in RETENTION.items():
        before, at, swept = boundary(kind)
        lines.append(f"{kind:<8} 期限 {label(td)}：1秒前={visible(before)} ちょうど={visible(at)} 掃除={swept}件")
    return lines


if __name__ == "__main__":
    print("\n".join(report()))
