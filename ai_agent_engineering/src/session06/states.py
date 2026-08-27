#!/usr/bin/env python3
"""セッション6：状態の型と、状態機械の定義。

会話履歴（LLM に渡すメッセージ列）と、アプリケーション状態（次の行動を決めるのに
必要な最小限）を**分けて**持つのがこの章の中心である。ここに置くのは後者だけ。

状態に入れる基準:
  - 次の行動を決めるのに使う      → 入れる（規程・申請一覧・違反の一覧・予約枠）
  - 記録として残したいだけ        → 入れない（軌跡に残す。search_docs の本文など）
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.state import Machine  # noqa: E402

# ---------------------------------------------------------------------------
# 状態と遷移。{現在の状態: {イベント: 次の状態}}
#   分岐 = 同じ状態から出る複数の遷移（checking から2本出ている）
#   ループ = 自分自身へ戻る遷移（collecting）と往復（booking ⇄ rescheduling）
# ---------------------------------------------------------------------------
TRANSITIONS: dict[str, dict[str, str]] = {
    "planning": {"plan_ready": "collecting", "fatal": "failed"},
    "collecting": {"need_more": "collecting", "collected": "checking", "fatal": "failed"},
    "checking": {"violation_found": "drafting", "no_violation": "wrapping_up",
                 "fatal": "failed"},
    "drafting": {"draft_saved": "booking", "fatal": "failed"},
    "booking": {"booked": "done", "conflict": "rescheduling", "fatal": "failed"},
    "rescheduling": {"slot_chosen": "booking", "no_slot": "wrapping_up", "fatal": "failed"},
    "wrapping_up": {"reported": "done", "fatal": "failed"},
}

# 出口のない状態（ここに来たら走行は終わり）
TERMINAL = ("done", "failed")

# 状態ごとに使ってよいツール（S04 の許可リストを「状態」に紐づける）
STATE_TOOLS: dict[str, tuple[str, ...]] = {
    "planning": (),
    "collecting": ("get_policy", "list_expenses", "search_docs"),
    "checking": (),
    "drafting": ("write_file",),
    "booking": ("book_room",),
    "rescheduling": (),
    "wrapping_up": ("write_file",),
    "done": (),
    "failed": (),
}

# 同じ状態に留まってよい回数の上限。ループには必ず上限を置く
LOOP_LIMITS: dict[str, int] = {"collecting": 3, "rescheduling": 2}

# サブゴール単位の粒度で保存するとき、保存する状態（ここに入ったときだけ保存する）
CHECKPOINT_STATES = ("checking", "booking", "done")

# 収集が終わったと判断するのに必要なツール（これが state に揃うまで collecting に留まる）
REQUIRED_SOURCES = ("get_policy", "list_expenses")

# 状態に本文まで保存するツール。search_docs は判断に使わないので保存しない
MATERIAL_TOOLS = ("get_policy", "list_expenses")

# 予約を取り直すときの候補枠。乱数を使わず、固定の順に試す
SLOTS = ("10:00", "11:00", "14:00")

# 規程「1件5万円以上は事前承認が必要」から取った金額基準
THRESHOLD = 50_000


def build_machine(initial: str = "planning") -> Machine:
    """状態機械を作る。再開時は保存されていた状態から作り直す。"""
    if initial not in TRANSITIONS and initial not in TERMINAL:
        raise ValueError(f"未定義の状態です: {initial!r}")
    return Machine(initial, TRANSITIONS)


# ---------------------------------------------------------------------------
# アプリケーション状態。JSON に落とせる形だけで構成する（チェックポイントに保存する）
# ---------------------------------------------------------------------------
@dataclass
class TaskState:
    task_id: str
    state: str = "planning"
    threshold: int = THRESHOLD          # 判断基準も状態に含める（再開後にぶれないため）
    visits: dict = field(default_factory=dict)      # 状態ごとの滞在回数（ループ上限用）
    materials: dict = field(default_factory=dict)   # ツール名 → 判断に使う本文
    violations: list = field(default_factory=list)  # 規程違反の疑いがある申請ID
    report_path: str | None = None
    booking: dict | None = None
    slot_index: int = 0
    pending: dict | None = None         # 実行しようとしている副作用（write-ahead 用）
    done_keys: list = field(default_factory=list)   # 実行し終えた副作用の目印
    llm_calls: int = 0                  # これまでにモデルに聞いた回数（再開位置の同期用）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        return cls(**data)

    def prompt_view(self) -> dict:
        """プロンプトに載せる「状態の投影」。

        状態そのものではなく、そこから毎回作り直した要約を渡す。
        向きは常に 状態 → プロンプト の一方向。逆流させない（本文のアンチパターン）。
        """
        return {
            "現在の段階": self.state,
            "取得済みの材料": sorted(self.materials),
            "規程違反の疑い": self.violations,
            "レポート": self.report_path,
            "予約": self.booking,
            "この段階で使えるツール": list(STATE_TOOLS.get(self.state, ())),
        }


def find_violations(table: str, threshold: int = THRESHOLD) -> list[str]:
    """申請一覧のテキストから「金額が基準以上なのに submitted のまま」を拾う。

    `list_expenses` の1行は
      EXP-0001 | 佐藤 健 | 3200 | 交通費 | approved | 2026-08-01
    の形。見出し行は expense_id で始まらないので自然に除かれる。
    """
    found: list[str] = []
    for line in table.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 6 or not cols[0].startswith("EXP-"):
            continue
        if not cols[2].isdigit():
            continue
        if int(cols[2]) >= threshold and cols[4] == "submitted":
            found.append(cols[0])
    return found


def render_report(st: TaskState) -> str:
    """レポート本文を**状態から**組み立てる。

    本文のような大きなデータはモデルに書かせない。状態が正しければ本文は決まるので、
    毎回同じ文字列になり、テストできる。
    """
    lines = [
        "# 規程改定の影響調査（自動生成）",
        "",
        f"- タスク: {st.task_id}",
        f"- 判定基準: 1件 {st.threshold:,} 円以上は事前承認が必要",
        f"- 規程違反の疑い: {len(st.violations)} 件",
        "",
        "## 対象の申請",
        "",
    ]
    if st.violations:
        for expense_id in st.violations:
            lines.append(f"- {expense_id}: 基準額以上だが submitted のまま（事前承認の記録なし）")
    else:
        lines.append("- 該当なし")
    lines += ["", "## 次にやること", "", "- 所属長へ事前承認の有無を確認する", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_machine().to_mermaid())
