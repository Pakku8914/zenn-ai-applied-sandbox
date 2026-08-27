#!/usr/bin/env python3
"""長期メモリの層 — 外に置き、期限を付け、出典を照合する。

`agentkit.memory.LongTermMemory` は `remember` / `recall` / `forget_all` の
3つしか持たない。実務で必要になる次の3つをこの層で足す（agentkit は変更しない）。

  - 忘却設計: 期限（`expires_on`）と重要度で、覚え続けるものを絞る
  - 汚染対策: 出典を残し、外部の事実と照合して矛盾する記憶を破棄する
  - いつ引くか: 毎回引く / 引かない / 必要な直前だけ引く のコストと失敗を数える

    python src/session07/longterm.py
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

from agentkit.biztools import CONFLICT_SLOTS, DATA, book_room  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.memory import LongTermMemory  # noqa: E402
from agentkit.tools import ToolError  # noqa: E402

CANDIDATES = {"みなと": ("10:00", "11:00"),
              "うみかぜ": ("09:00", "10:00"),
              "大会議室": ("13:00", "14:00")}
STEPS = ("計画", "確認", "予約")   # 予約タスクの3段階。引く回数を数えるための骨組み


class AuditMemory:
    """長期メモリに「期限・重要度・出典」を持たせた層。"""

    def __init__(self, name: str = "session07", clock=None) -> None:
        self.ltm = LongTermMemory(name)
        self.clock = clock or FixedClock()
        self.recalls = 0

    # -- 書く ---------------------------------------------------------------
    def remember(self, key: str, body: str, *, kind: str = "fact",
                 importance: int = 1, expires_on: str | None = None,
                 source: str = "") -> None:
        """覚える。**出典と期限を必ず一緒に残す**（後で捨てられるようにするため）。"""
        value = json.dumps({"body": body, "kind": kind, "expires_on": expires_on,
                            "source": source, "at": self.clock.today()},
                           ensure_ascii=False)
        self.ltm.remember(key, value, importance)

    def rows(self) -> list[dict]:
        """保存されている記憶を、書いた順に返す（期限切れも含む）。"""
        path = Path(self.ltm.path)
        if not path.exists():
            return []
        out = []
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            out.append({"key": row["key"], "importance": row["importance"],
                        **json.loads(row["value"])})
        return out

    # -- 引く ---------------------------------------------------------------
    def expired(self, row: dict) -> bool:
        return bool(row.get("expires_on")) and row["expires_on"] < self.clock.today()

    def recall(self, query: str, limit: int = 3) -> list[dict]:
        """キーワードで引く。期限切れは返さない。"""
        self.recalls += 1
        hits = self.ltm.recall(query, limit=limit * 3)
        out = []
        for hit in hits:
            row = {"key": hit["key"], "importance": hit["importance"],
                   **json.loads(hit["value"])}
            if not self.expired(row):
                out.append(row)
        return out[:limit]

    def recall_lines(self, query: str, limit: int = 3) -> list[str]:
        """外部化した記録から**行単位で**引き戻す。

        全部戻すとまた溢れるので、引き戻すのは一致した行だけにする。
        """
        self.recalls += 1
        out: list[str] = []
        for row in self.rows():
            if self.expired(row):
                continue
            for line in row["body"].split("\n"):
                if query in line and len(out) < limit:
                    out.append(line)
        return out

    def known_conflicts(self) -> set[tuple[str, str]]:
        """「競合する」と覚えている枠。期限切れの記憶は使わない。"""
        return {(row["body"].split()[0], row["body"].split()[1])
                for row in self.rows()
                if row.get("kind") == "conflict" and not self.expired(row)
                and "競合" in row["body"]}

    # -- 忘れる -------------------------------------------------------------
    def forget_expired(self) -> int:
        """期限切れを落として書き戻す（追記式なので掃除が必要）。"""
        keep = [row for row in self.rows() if not self.expired(row)]
        dropped = len(self.rows()) - len(keep)
        with Path(self.ltm.path).open("w", encoding="utf-8") as f:
            for row in keep:
                f.write(json.dumps(
                    {"key": row["key"], "importance": row["importance"],
                     "value": json.dumps({"body": row["body"], "kind": row["kind"],
                                          "expires_on": row["expires_on"],
                                          "source": row["source"], "at": row["at"]},
                                         ensure_ascii=False)},
                    ensure_ascii=False) + "\n")
        return dropped

    def forget(self, key: str) -> int:
        """鍵を指定して忘れる（汚染された記憶の破棄に使う）。"""
        rows = self.rows()
        keep = [row for row in rows if row["key"] != key]
        with Path(self.ltm.path).open("w", encoding="utf-8") as f:
            for row in keep:
                f.write(json.dumps(
                    {"key": row["key"], "importance": row["importance"],
                     "value": json.dumps({"body": row["body"], "kind": row["kind"],
                                          "expires_on": row["expires_on"],
                                          "source": row["source"], "at": row["at"]},
                                         ensure_ascii=False)},
                    ensure_ascii=False) + "\n")
        return len(rows) - len(keep)

    def clear(self) -> None:
        self.ltm.forget_all()
        self.recalls = 0

    # -- 照合（汚染の検出）--------------------------------------------------
    def audit_facts(self) -> list[dict]:
        """覚えている「競合する枠」を外部の事実と突き合わせる。

        記憶は**検証できる形**で持つ。照合できない記憶は、間違っていても
        永久に残り続ける（これがメモリの汚染）。
        """
        out = []
        for row in self.rows():
            if row.get("kind") != "conflict":
                continue
            parts = row["body"].split()
            slot = (parts[0], parts[1])
            remembered = "競合" in row["body"]
            actual = slot in CONFLICT_SLOTS
            out.append({"鍵": row["key"], "記憶": row["body"],
                        "出典": row["source"] or "（なし）",
                        "一致": remembered == actual,
                        "実際": "競合する" if actual else "予約できる"})
        return out


# ---------------------------------------------------------------------------
# いつ引くか — 3方式のコストと失敗を数える
# ---------------------------------------------------------------------------
def bookings_rows() -> int:
    path = DATA / "bookings.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


def reset_data() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_data.py")],
                   check=True, capture_output=True)


def try_booking(mode: str, memory: AuditMemory, room: str = "みなと") -> dict:
    """会議室を押さえる。`mode` で「いつ長期メモリを引くか」を変える。

    mode: "none"（引かない）/ "always"（毎ステップ引く）/ "conditional"（予約の直前だけ）
    """
    if mode not in ("none", "always", "conditional"):
        raise ValueError(f"mode は none / always / conditional です: {mode!r}")
    before = memory.recalls
    avoid: set[tuple[str, str]] = set()
    attempts = 0
    failures = 0
    booked = None
    for step in STEPS:
        if mode == "always" or (mode == "conditional" and step == "予約"):
            memory.recall(f"{room} の予約")      # 引いた回数を数えるために通す
            avoid = memory.known_conflicts()
        if step != "予約":
            continue
        for slot in CANDIDATES[room]:
            if (room, slot) in avoid:
                continue                          # 覚えている競合枠は試さない
            attempts += 1
            try:
                book_room(room, slot)
            except ToolError:
                failures += 1
                memory.remember(f"conflict:{room} {slot}", f"{room} {slot} は競合する",
                                kind="conflict", importance=3, source="book_room の失敗")
                continue
            booked = slot
            break
    return {"方式": mode, "引いた回数": memory.recalls - before, "予約の試行": attempts,
            "失敗": failures, "押さえた枠": booked, "予約された行数": bookings_rows()}


def recall_modes() -> list[dict]:
    """3方式を同じ前提（競合を1件覚えている状態）で走らせて比べる。"""
    rows = []
    for mode in ("none", "always", "conditional"):
        reset_data()
        memory = AuditMemory("recall_modes")
        memory.clear()
        memory.remember("conflict:みなと 10:00", "みなと 10:00 は競合する",
                        kind="conflict", importance=3, source="前回の実行")
        rows.append(try_booking(mode, memory))
    reset_data()
    return rows


def pollution_report() -> dict:
    """汚染された記憶が何を引き起こすかを2種類に分けて観測する。"""
    reset_data()
    memory = AuditMemory("pollution")
    memory.clear()
    # ① 偽の競合。実際は予約できるのに避け続ける（失敗が出ないので気づけない）
    #    出典を空にしてあるのが要点。どこから来た記憶か分からないと検証もできない
    memory.remember("memo:うみかぜ 09:00", "うみかぜ 09:00 は競合する",
                    kind="conflict", importance=3, source="")
    # ② 見落とし。実際は競合するのに空きだと覚えている（失敗として現れる）
    memory.remember("memo:大会議室 13:00", "大会議室 13:00 は予約できる",
                    kind="conflict", importance=3, source="")
    false_conflict = try_booking("conditional", memory, room="うみかぜ")
    missed = try_booking("conditional", memory, room="大会議室")
    audit = memory.audit_facts()
    dropped = sum(memory.forget(row["鍵"]) for row in audit if not row["一致"])
    reset_data()
    fixed = try_booking("conditional", memory, room="うみかぜ")
    reset_data()
    return {"偽の競合": false_conflict, "見落とし": missed,
            "照合結果": audit, "破棄した記憶": dropped, "破棄後": fixed}


if __name__ == "__main__":
    print("=== いつ引くか（同じ記憶・同じタスク）===")
    print(f"{'方式':<14}{'引いた回数':>10}{'予約の試行':>10}{'失敗':>6}{'押さえた枠':>10}")
    for row in recall_modes():
        print(f"{row['方式']:<14}{row['引いた回数']:>10}{row['予約の試行']:>10}"
              f"{row['失敗']:>6}{row['押さえた枠']:>10}")

    print("\n=== メモリの汚染 ===")
    report = pollution_report()
    for label in ("偽の競合", "見落とし", "破棄後"):
        row = report[label]
        print(f"{label:<8} 試行={row['予約の試行']} 失敗={row['失敗']} "
              f"押さえた枠={row['押さえた枠']}")
    for row in report["照合結果"]:
        print(f"  {'一致' if row['一致'] else '不一致'}: {row['記憶']}"
              f"（実際は{row['実際']} / 出典 {row['出典']}）")
    print(f"  破棄した記憶: {report['破棄した記憶']} 件")
