"""承認ゲート（セッション10の参照実装）。

承認は「中断して待つ」形で実装する。承認済みの内容と実行する内容がずれないよう、
引数のハッシュで固定するのが要点。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import ToolCall, Trajectory

APPROVAL_DIR = Path(__file__).resolve().parent.parent / "traces" / "approvals"


def call_digest(call: ToolCall) -> str:
    """ツール呼び出しの内容から決定的なハッシュを作る。

    承認時と実行時でこの値が一致することを確認すれば、
    「承認したのと違う内容が実行される」事故を防げる。
    """
    blob = json.dumps({"name": call.name, "args": call.args}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class ApprovalGate:
    """承認の記録を持ち、承認済みかどうかを判定する。

    check() の戻り値:
      True  … 承認済み（実行してよい）
      False … 却下済み（実行しない）
      None  … 未判断（中断して人間に渡す）
    """

    task_id: str
    decisions: dict[str, bool] = field(default_factory=dict)  # digest -> approved
    threshold_yen: int = 50_000

    def needs_approval(self, call: ToolCall) -> bool:
        """金額の閾値による判定。ツール側の `requires_approval` と併用する。"""
        amount = call.args.get("amount")
        if isinstance(amount, (int, float)) and amount >= self.threshold_yen:
            return True
        return call.name in ("send_message", "delete_record")

    def check(self, call: ToolCall, traj: Trajectory | None = None) -> bool | None:
        return self.decisions.get(call_digest(call))

    def approve(self, call: ToolCall) -> str:
        digest = call_digest(call)
        self.decisions[digest] = True
        return digest

    def reject(self, call: ToolCall) -> str:
        digest = call_digest(call)
        self.decisions[digest] = False
        return digest

    def render_request(self, call: ToolCall) -> str:
        """承認者に見せる情報。何をしようとしているかを一目で分かる形にする。"""
        args = "\n".join(f"  - {k}: {v}" for k, v in sorted(call.args.items()))
        return (f"【承認依頼】{call.name}\n"
                f"内容:\n{args}\n"
                f"照合用ハッシュ: {call_digest(call)}\n"
                f"※ 実行時にこのハッシュが一致することを確認します")

    def save(self) -> Path:
        APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
        path = APPROVAL_DIR / f"{self.task_id}.json"
        path.write_text(json.dumps({"task_id": self.task_id, "decisions": self.decisions,
                                    "threshold_yen": self.threshold_yen},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, task_id: str) -> "ApprovalGate":
        path = APPROVAL_DIR / f"{task_id}.json"
        if not path.exists():
            return cls(task_id=task_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(task_id=data["task_id"], decisions=data.get("decisions", {}),
                   threshold_yen=data.get("threshold_yen", 50_000))
