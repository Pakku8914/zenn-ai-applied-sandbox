#!/usr/bin/env python3
"""セッション10：承認の監査ログ。

「誰が・いつ・何を・どういう理由で承認したか」を後から追える形で残す。
1行1件の JSONL にし、各行に**前の行のハッシュ**を含めて鎖にする。
途中の1行を書き換えると、そこから先の鎖が合わなくなるので改ざんを検出できる。

時刻は `FixedClock` を注入するので、本書では全行が同じ `at` になる。
順序は `seq` とハッシュ鎖で保証しており、時刻には依存しない設計にしている。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.clock import FixedClock  # noqa: E402

AUDIT_DIR = ROOT / "traces" / "audit"

# ハッシュの対象にする項目。`hash` 自身は含めない
FIELDS = ("seq", "at", "actor", "event", "tool", "digest", "mode", "detail", "prev")


def row_hash(row: dict) -> str:
    """1行の内容と直前のハッシュから、その行のハッシュを作る。"""
    blob = json.dumps({k: row[k] for k in FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


@dataclass
class AuditLog:
    """承認の監査ログ（追記専用）。"""

    task_id: str
    clock: object = None
    directory: Path | None = None

    def __post_init__(self) -> None:
        self.clock = self.clock or FixedClock()
        self.directory = Path(self.directory) if self.directory else AUDIT_DIR

    @property
    def path(self) -> Path:
        return self.directory / f"{self.task_id}.jsonl"

    def reset(self) -> None:
        """演習用に空にする（実運用の監査ログは消さない）。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line)
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def append(self, event: str, *, actor: str = "agent", tool: str = "",
               digest: str = "", mode: str = "", detail: str = "") -> dict:
        rows = self.rows()
        row = {"seq": len(rows) + 1,
               "at": self.clock.now().isoformat(),
               "actor": actor, "event": event, "tool": tool,
               "digest": digest, "mode": mode, "detail": detail,
               "prev": rows[-1]["hash"] if rows else "genesis"}
        row["hash"] = row_hash(row)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def events(self) -> list[str]:
        return [r["event"] for r in self.rows()]

    def actors(self) -> list[str]:
        return [r["actor"] for r in self.rows()]

    def verify_chain(self) -> tuple[bool, int]:
        """鎖を検証する。戻り値は（健全か, 最初に壊れている行の添字）。"""
        prev = "genesis"
        for index, row in enumerate(self.rows()):
            if row.get("seq") != index + 1:
                return False, index
            if row.get("prev") != prev:
                return False, index
            if row.get("hash") != row_hash(row):
                return False, index
            prev = row["hash"]
        return True, -1

    def render(self) -> str:
        return "\n".join(
            f"[{r['seq']}] {r['event']} / {r['tool']} / {r['actor']} / {r['detail']}"
            for r in self.rows())


def rewrite_rows(log: AuditLog, rows: list[dict]) -> None:
    """監査ログを丸ごと書き直す（削除・挿入の再現。演習でのみ使う）。"""
    log.directory.mkdir(parents=True, exist_ok=True)
    with log.path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tamper(log: AuditLog, index: int, detail: str) -> None:
    """監査ログの1行を書き換える（改ざんの再現。演習でのみ使う）。"""
    rows = log.rows()
    rows[index]["detail"] = detail  # ハッシュは作り直さない（つじつまが合わなくなる）
    rewrite_rows(log, rows)


if __name__ == "__main__":
    demo = AuditLog("DEMO-audit")
    demo.reset()
    demo.append("requested", tool="submit_expense", mode="approve", detail="金額 68,000 円")
    demo.append("approved", actor="鈴木 彩", tool="submit_expense", mode="approve", detail="1/1")
    demo.append("executed", tool="submit_expense", mode="approve", detail="EXP-0007")
    print(demo.render())
    print("鎖の検証:", demo.verify_chain())
    tamper(demo, 1, "2/2 だったことにする")
    print("改ざん後:", demo.verify_chain())
