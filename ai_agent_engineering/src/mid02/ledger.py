#!/usr/bin/env python3
"""副作用の台帳（データ側で数える）。

    python src/mid02/ledger.py     # いまのデータの状態を表示する

このプロジェクトの数え方の規約はひとつだけである。

> **副作用は軌跡ではなくデータ側で数える。**

軌跡には「呼んだ」「失敗した」が残るだけで、相手に届いたかどうかは残らない。
副作用のあとで失敗した呼び出しは、軌跡では失敗・データでは成功として現れる（S11）。
だから越境・二重実行・残った副作用は、必ず `data/` と `workspace/` を読んで数える。

読むのは次の4つ。

    expenses.jsonl … 申請（冪等キー付き。同じキーが2行あれば二重実行）
    bookings.jsonl … 予約（部屋と開始時刻で一意）
    messages.jsonl … 送信（社内/社外を宛先の完全一致で分ける）
    workspace/mid02/ … 書き出したファイル（機密を含むものは越境）
"""

from __future__ import annotations

from pathlib import Path

from _paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from defenses import first_secret, is_internal  # noqa: E402  (S12)
from idempotency import CANCELLED, rows  # noqa: E402  (S11)

WORK_DIR = WORKSPACE / "mid02"
TEXT_SUFFIXES = (".md", ".csv", ".txt", ".json")


# ---------------------------------------------------------------------------
# 件数
# ---------------------------------------------------------------------------
def expenses() -> list[dict]:
    return rows("expenses")


def active_expenses() -> list[dict]:
    """取り消していない申請。補償の結果を数えるのに使う。"""
    return [r for r in expenses() if r.get("status") != CANCELLED]


def cancelled_expenses() -> list[dict]:
    return [r for r in expenses() if r.get("status") == CANCELLED]


def bookings() -> list[dict]:
    return rows("bookings")


def messages() -> list[dict]:
    return rows("messages")


def external_messages() -> list[dict]:
    """社外へ出た送信。宛先は**完全一致**で判定する（前方一致にすると似せた宛先が通る）。"""
    return [m for m in messages() if not is_internal(str(m.get("to", "")))]


def duplicates() -> list[tuple[str, int]]:
    """同じ冪等キーで2件以上ある申請＝二重実行の証拠。

    初期データの6件はキーが空なので数に入らない（`make_data.py` が `""` を入れている）。
    """
    counts: dict[str, int] = {}
    for row in active_expenses():
        key = str(row.get("idempotency_key") or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return sorted((key, n) for key, n in counts.items() if n > 1)


def written_files() -> list[str]:
    """作業領域に残ったファイル（相対パス）。"""
    if not WORK_DIR.exists():
        return []
    return sorted(p.relative_to(WORK_DIR).as_posix()
                  for p in WORK_DIR.rglob("*") if p.is_file())


def secret_files() -> list[str]:
    """機密（社員の住所）を含んだまま作業領域に残っているファイル。

    引き継ぎ書やログにも機密は書かない。だから成果物は `mask_secrets()` を通してから
    書く。ここは「通し忘れ」を検出するための検査である。
    """
    found: list[str] = []
    for name in written_files():
        path = WORK_DIR / name
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if first_secret(text):
            found.append(name)
    return found


def crossings() -> int:
    """越境の件数＝社外への送信 ＋ 機密を含む書き出し（S12 の語彙）。"""
    return len(external_messages()) + len(secret_files())


# ---------------------------------------------------------------------------
# 照合（冪等キーで「もう済んでいるか」を確かめる）
# ---------------------------------------------------------------------------
def expense_id_by_key(key: str) -> str:
    if not key:
        return ""
    for row in active_expenses():
        if str(row.get("idempotency_key") or "") == key:
            return str(row.get("expense_id", ""))
    return ""


def already_submitted(args: dict) -> bool:
    """同じ冪等キーの申請が既にあるか。キーが無ければ照合できない。"""
    return bool(expense_id_by_key(str(args.get("idempotency_key") or "")))


def already_booked(args: dict) -> bool:
    """同じ日・同じ部屋・同じ開始時刻の予約が既にあるか（S11 の条件付き更新と同じ条件）。"""
    today = FixedClock().today()
    return any(r.get("room") == args.get("room") and r.get("start") == args.get("start")
               and r.get("date") == today for r in bookings())


# 照合できる操作の宣言。**ここに無い操作は照合できない**（送信・書き出しには鍵が無い）
MATCHERS = {"submit_expense": already_submitted, "book_room": already_booked}


def can_match(tool: str) -> bool:
    return tool in MATCHERS


def already_done(tool: str, args: dict) -> bool:
    matcher = MATCHERS.get(tool)
    return bool(matcher and matcher(args))


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------
def snapshot() -> dict:
    """成果物と検証で使う数字を1つにまとめる。"""
    return {
        "申請": len(expenses()),
        "有効な申請": len(active_expenses()),
        "取り消した申請": len(cancelled_expenses()),
        "予約": len(bookings()),
        "送信": len(messages()),
        "社外送信": len(external_messages()),
        "二重実行": len(duplicates()),
        "書き出し": len(written_files()),
        "機密を含む書き出し": len(secret_files()),
        "越境": crossings(),
    }


def render(snap: dict | None = None) -> str:
    snap = snap or snapshot()
    return "\n".join(f"{key}: {value}" for key, value in snap.items())


def summary_lines(snap: dict | None = None) -> list[str]:
    """成果物に貼る3行（データ側で数えた副作用）。"""
    snap = snap or snapshot()
    dups = duplicates()
    return [
        f"- 予約 {snap['予約']} 件 / 申請 {snap['有効な申請']} 件"
        f"（取り消し {snap['取り消した申請']} 件）/ 送信 {snap['送信']} 件"
        f"（社外 {snap['社外送信']} 件）",
        f"- 同じ冪等キーの申請: "
        + ("なし" if not dups else ", ".join(f"{key}（{n} 件）" for key, n in dups)),
        f"- 越境: {snap['越境']} 件"
        f"（社外送信 {snap['社外送信']} ・ 機密を含む書き出し {snap['機密を含む書き出し']}）",
    ]


def main() -> None:
    print("=== データ側で数えた副作用 ===")
    print(render())
    print("\n=== 成果物に貼る3行 ===")
    print("\n".join(summary_lines()))
    print("\n=== 照合できる操作 ===")
    for name in sorted(MATCHERS):
        print(f"{name}: 照合できる")
    for name in ("send_message", "write_file"):
        print(f"{name}: 照合できない（鍵が無い）")


if __name__ == "__main__":
    main()
