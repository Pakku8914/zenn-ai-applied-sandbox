#!/usr/bin/env python3
"""調査エージェントの状態機械と、アプリケーション状態（成果物②）。

    python src/mid01/machine.py    # 状態遷移図（Mermaid）を出力する

この章で分けて持つのは次の3つである。混ぜると、あとから何も説明できなくなる。

  状態       … どこまで進んだか（planning / collecting / ... / done / failed）
  停止理由   … なぜ止まったか（done / max_steps / loop_detected / error）
  結果       … 人に何を渡したか（report / partial / insufficient / handoff）

`agentkit.state.Machine` はそのまま使う。足したのは
「状態ごとの許可リスト」「同じ状態に留まってよい回数」「モデルに聞く状態」だけ。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from _paths import setup

ROOT = setup()

from agentkit.state import Machine  # noqa: E402

# ---------------------------------------------------------------------------
# 状態と遷移。{現在の状態: {イベント: 次の状態}}
#   分岐 = 同じ状態から出る複数の遷移（collecting から4本・checking から2本）
#   ループ = 自分自身へ戻る遷移（collecting / reporting）
#   異常系の出口 = insufficient（情報不足）/ stopping（上限到達）/ handoff（人へ渡す）
# ---------------------------------------------------------------------------
TRANSITIONS: dict[str, dict[str, str]] = {
    "planning": {"plan_ready": "collecting", "invalid_plan": "handoff"},
    "collecting": {"need_more": "collecting", "collected": "checking",
                   "not_found": "insufficient", "blocked": "handoff",
                   "over_budget": "stopping"},
    "checking": {"grounded": "drafting", "ungrounded": "insufficient",
                 "blocked": "handoff", "over_budget": "stopping"},
    "drafting": {"draft_saved": "reporting", "blocked": "handoff",
                 "over_budget": "stopping"},
    "reporting": {"reported": "done", "hallucinated": "reporting",
                  "blocked": "handoff", "over_budget": "stopping"},
    "insufficient": {"reported": "done", "blocked": "handoff"},
    "stopping": {"partial_saved": "done", "blocked": "handoff"},
    "handoff": {"escalated": "failed"},
}

# 出口のない状態（ここに来たら走行は終わり）
TERMINAL = ("done", "failed")

# 状態ごとに使ってよいツール（S04 の許可リストを「状態」に紐づける）
STATE_TOOLS: dict[str, tuple[str, ...]] = {
    "planning": (),
    "collecting": ("find_expenses", "get_policy", "search_docs"),
    "checking": (),
    "drafting": ("write_file",),
    "reporting": (),
    "insufficient": ("write_file",),
    "stopping": ("write_file",),
    "handoff": ("write_file",),
    "done": (),
    "failed": (),
}

# モデルに聞く状態。ここ以外は状態から決まるので聞かない（＝手数に数えない）
ASK_STATES = ("collecting", "reporting")

# 同じ状態に留まってよい回数の上限。ループには必ず上限を置く
LOOP_LIMITS: dict[str, int] = {"collecting": 3, "reporting": 2}

# 判定に使う材料（これがそろうまで collecting に留まる）
REQUIRED_SOURCES = ("get_policy", "find_expenses")

# 根拠として状態に採用するツール。search_docs は採用しない（信頼境界の線）
MATERIAL_TOOLS = ("get_policy", "find_expenses")

# 人に渡すものの種類と、その日本語ラベル
OUTCOMES = ("report", "partial", "insufficient", "handoff")
OUTCOME_LABELS = {
    "report": "報告",
    "partial": "打ち切り（部分結果）",
    "insufficient": "情報不足",
    "handoff": "引き継ぎ",
}

# 成果物の置き場所（workspace/ からの相対パス）
ARTIFACT_PATH = "mid01/report.md"
HANDOFF_PATH = "mid01/handoff.md"


def build_machine(initial: str = "planning") -> Machine:
    """状態機械を作る。未定義の状態から始めようとしたらそこで落とす。"""
    if initial not in TRANSITIONS and initial not in TERMINAL:
        raise ValueError(f"未定義の状態です: {initial!r}")
    return Machine(initial, TRANSITIONS)


def stage_error(state: str, name: str, allowed: tuple[str, ...]) -> str:
    """段階外のツール呼び出しを断るときのメッセージ。

    S04 の `is_actionable()` が True になる形にしてある（許容値と次の一手を含む）。
    断るだけでは、モデルは次に何をすればよいか分からない。
    """
    return (f"いまは '{state}' の段階なので、ツール '{name}' は実行できません。"
            f"この段階で使えるツール: {', '.join(allowed) if allowed else 'なし'}。")


# ---------------------------------------------------------------------------
# アプリケーション状態。JSON に落とせる形だけで構成する（S06 と同じ規約）
# ---------------------------------------------------------------------------
@dataclass
class ResearchState:
    task_id: str
    state: str = "planning"
    outcome: str = "report"              # 人に渡すものの種類
    threshold: int | None = None         # 判定基準（規程から抽出した金額）
    visits: dict = field(default_factory=dict)      # 状態ごとの滞在回数
    materials: dict = field(default_factory=dict)   # 根拠に採用したツール結果の本文
    sources: list = field(default_factory=list)     # 採用した出典（ツール名と引数）
    notes: list = field(default_factory=list)       # 参照したが採用しなかったもの
    findings: list = field(default_factory=list)    # 基準額以上で未承認の申請
    rejected: list = field(default_factory=list)    # 報告文を差し戻した理由
    handoff_reason: str = ""
    stopped_at: str = ""                 # どの段階で異常終了したか
    artifact: str = ""                   # 実際に書いたファイル
    llm_calls: int = 0                   # モデルに聞いた回数
    max_llm_calls: int = 6               # 手数の上限（状態にも持たせて再現できるようにする）

    def to_dict(self) -> dict:
        return asdict(self)

    def missing_sources(self) -> list[str]:
        """まだそろっていない材料。情報不足の申し送りにそのまま載る。"""
        return [name for name in REQUIRED_SOURCES if name not in self.materials]

    def prompt_view(self) -> dict:
        """プロンプトに載せる「状態の投影」。

        状態そのものではなく、そこから毎回作り直した要約を渡す（S06）。
        向きは常に 状態 → プロンプト の一方向。逆流させない。
        """
        return {
            "現在の段階": self.state,
            "判定基準": f"{self.threshold:,} 円以上" if self.threshold else "未確認",
            "採用した根拠": list(self.sources),
            "該当した申請": [f["expense_id"] for f in self.findings],
            "そろっていない材料": self.missing_sources(),
            "差し戻しの理由": list(self.rejected),
            "この段階で使えるツール": list(STATE_TOOLS.get(self.state, ())),
        }


if __name__ == "__main__":
    print(build_machine().to_mermaid())
