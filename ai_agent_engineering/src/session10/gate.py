#!/usr/bin/env python3
"""セッション10：承認ゲート（`agentkit.approval.ApprovalGate` の拡張）。

`ApprovalGate` は「決定を覚える」「内容をハッシュで固定する」までを持っている。
実務で足りないのは次の4つで、それをこの層で足す。

  1. 段階（自動実行／事後通知／事前承認／二重承認）を引数まで見て決める
  2. 承認者に見せる情報（何を・なぜ・実行するとどうなるか・期限）を組み立てる
  3. 却下・条件付き承認・期限切れを扱う
  4. 監査ログに残す（誰が・いつ・何を・どういう理由で）

`agentkit` は1行も変更していない。`call_digest` と `render_request` はそのまま使う。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.approval import ApprovalGate, call_digest  # noqa: E402
from agentkit.biztools import DATA  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.models import ToolCall, Trajectory  # noqa: E402
from audit import AuditLog  # noqa: E402
from policy import (MODE_LABEL, THRESHOLD_YEN, TTL_HOURS, Decision,  # noqa: E402
                     is_external)

GATE_DIR = ROOT / "traces" / "approvals" / "session10"


# ---------------------------------------------------------------------------
# 承認者に見せる「実行するとどうなるか」
# ---------------------------------------------------------------------------
def _rows(name: str) -> list[dict]:
    path = DATA / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def impact_lines(call: ToolCall) -> list[str]:
    """影響の見積もり。件数・金額・宛先のように**数えられる形**で出す。"""
    if call.name == "submit_expense":
        rows = _rows("expenses")
        total = sum(int(r.get("amount", 0)) for r in rows)
        amount = int(call.args.get("amount", 0) or 0)
        return [f"経費申請: {len(rows)} 件 / {total:,} 円 → {len(rows) + 1} 件 / {total + amount:,} 円",
                f"追加される行: {call.args.get('employee')} / {amount:,} 円 / {call.args.get('category')}",
                "取り下げには承認者の操作が必要です（自動では戻せません）"]
    if call.name == "send_message":
        to = str(call.args.get("to", ""))
        body = str(call.args.get("body", ""))
        return [f"宛先: {to}（{'社外' if is_external(to) else '社内'}）",
                f"本文: {len(body)} 文字 / 先頭: {body[:24]}",
                f"送信済みの件数: {len(_rows('messages'))} 件 → {len(_rows('messages')) + 1} 件（送信は取り消せません）"]
    return [f"影響の見積もりが未実装の操作です（{call.name}）。実行前に人が内容を確認してください。"]


def check_conditional(call: ToolCall, changes: dict) -> None:
    """条件付き承認の変更内容を検査する。おかしければ例外にする。"""
    if not changes:
        raise ValueError("条件付き承認には変更内容が必要です。")
    unknown = [k for k in changes if k not in call.args]
    if unknown:
        raise ValueError(f"元の呼び出しに無い引数は追加できません: {unknown}")
    if "amount" in changes and "idempotency_key" not in changes:
        raise ValueError("金額を変えると別の申請になります。"
                         "idempotency_key（日付-社員ID-金額）も一緒に変えてください。")


# ---------------------------------------------------------------------------
class ReviewGate(ApprovalGate):
    """承認の記録・依頼・却下・条件付き承認・期限・監査ログを持つゲート。"""

    def __init__(self, task_id: str, *, clock=None, ttl_hours: int = TTL_HOURS,
                 threshold_yen: int = THRESHOLD_YEN, directory: Path | None = None,
                 audit: AuditLog | None = None, decisions: dict | None = None,
                 requests: dict | None = None, signoffs: dict | None = None,
                 replacements: dict | None = None,
                 reject_reasons: dict | None = None) -> None:
        super().__init__(task_id=task_id, decisions=dict(decisions or {}),
                         threshold_yen=threshold_yen)
        self.clock = clock or FixedClock()
        self.ttl_hours = ttl_hours
        self.directory = Path(directory) if directory else GATE_DIR
        self.audit = audit or AuditLog(task_id, clock=self.clock)
        self.requests: dict[str, dict] = {k: dict(v) for k, v in (requests or {}).items()}
        self.signoffs: dict[str, list] = {k: list(v) for k, v in (signoffs or {}).items()}
        self.replacements: dict[str, dict] = {k: dict(v) for k, v in (replacements or {}).items()}
        self.reject_reasons: dict[str, str] = dict(reject_reasons or {})

    # -- 依頼 ---------------------------------------------------------------
    def request(self, call: ToolCall, decision: Decision) -> dict:
        """承認依頼を作る。同じ内容で2回呼んでも依頼は1件しか増えない。"""
        digest = call_digest(call)
        existing = self.requests.get(digest)
        if existing is not None:
            return existing
        now = self.clock.now()
        request = {
            "digest": digest, "tool": call.name, "args": dict(call.args),
            "mode": decision.mode, "reasons": list(decision.reasons),
            "requested_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=self.ttl_hours)).isoformat(),
            "approvers_required": 2 if decision.mode == "dual" else 1,
        }
        self.requests[digest] = request
        self.audit.append("requested", tool=call.name, digest=digest, mode=decision.mode,
                          detail="; ".join(decision.reasons))
        return request

    def required(self, digest: str) -> int:
        request = self.requests.get(digest)
        return int(request["approvers_required"]) if request else 1

    def expires_at(self, digest: str) -> str:
        request = self.requests.get(digest)
        return request["expires_at"] if request else ""

    def is_expired(self, digest: str) -> bool:
        request = self.requests.get(digest)
        if not request:
            return False
        return self.clock.now() > datetime.fromisoformat(request["expires_at"])

    def approvers_of(self, digest: str) -> list[str]:
        return list(self.signoffs.get(digest, []))

    def reject_reason(self, digest: str) -> str:
        return self.reject_reasons.get(digest, "")

    def replacement_for(self, digest: str) -> dict | None:
        replaced = self.replacements.get(digest)
        return dict(replaced) if replaced is not None else None

    # -- 人間の判断 ---------------------------------------------------------
    def approve(self, call: ToolCall, by: str = "承認者", note: str = "") -> str:
        """承認する。二重承認なら必要な人数が揃ったときだけ実行可能になる。"""
        digest = call_digest(call)
        names = self.signoffs.setdefault(digest, [])
        if by in names:  # 同じ人が2回押しても1票
            return digest
        names.append(by)
        required = self.required(digest)
        if len(names) >= required:
            self.decisions[digest] = True
        self.audit.append("approved", actor=by, tool=call.name, digest=digest,
                          mode=self.requests.get(digest, {}).get("mode", ""),
                          detail=f"{len(names)}/{required} {note}".strip())
        return digest

    def reject(self, call: ToolCall, by: str = "承認者", reason: str = "") -> str:
        """却下する。承認は全員そろって初めて成立するが、却下は1人で成立する。"""
        digest = call_digest(call)
        self.decisions[digest] = False
        self.reject_reasons[digest] = reason or "理由の記録がありません"
        self.audit.append("rejected", actor=by, tool=call.name, digest=digest,
                          mode=self.requests.get(digest, {}).get("mode", ""),
                          detail=self.reject_reasons[digest])
        return digest

    def approve_with_changes(self, call: ToolCall, changes: dict, by: str = "承認者",
                             note: str = "") -> ToolCall:
        """条件付き承認。**書き換えた内容そのもの**を承認する。

        「金額を下げれば可」は、元の内容の承認ではなく別の内容の承認である。
        だから新しいハッシュで記録し、元のハッシュには承認を与えない。
        """
        check_conditional(call, changes)
        original = call_digest(call)
        amended = ToolCall(call.call_id, call.name, {**call.args, **changes})
        new_digest = call_digest(amended)
        base = dict(self.requests.get(original, {}))
        base.update({"digest": new_digest, "args": dict(amended.args),
                     "amended_from": original})
        base.setdefault("tool", call.name)
        base.setdefault("mode", "approve")
        base.setdefault("approvers_required", 1)
        base.setdefault("reasons", [])
        base.setdefault("requested_at", self.clock.now().isoformat())
        base.setdefault("expires_at",
                        (self.clock.now() + timedelta(hours=self.ttl_hours)).isoformat())
        self.requests[new_digest] = base
        self.replacements[original] = dict(amended.args)
        names = self.signoffs.setdefault(new_digest, [])
        if by not in names:
            names.append(by)
        if len(names) >= self.required(new_digest):
            self.decisions[new_digest] = True
        diff = ", ".join(f"{k}: {call.args.get(k)} → {v}" for k, v in sorted(changes.items()))
        self.audit.append("conditionally_approved", actor=by, tool=call.name,
                          digest=new_digest, mode=base.get("mode", ""),
                          detail=f"{note}（変更: {diff}）")
        return amended

    # -- 承認者に見せる情報 -------------------------------------------------
    def render(self, call: ToolCall, decision: Decision | None = None,
               traj: Trajectory | None = None) -> str:
        """承認画面に出す情報。判断に必要なものだけを並べる。"""
        digest = call_digest(call)
        request = self.requests.get(digest)
        mode = request["mode"] if request else (decision.mode if decision else "approve")
        reasons = request["reasons"] if request else (decision.reasons if decision else [])
        required = self.required(digest) if request else (2 if mode == "dual" else 1)
        lines = [super().render_request(call), "",
                 f"■ 判定: {MODE_LABEL[mode]}（必要な承認者 {required} 名）",
                 "■ なぜ承認が必要か"]
        lines += [f"  - {reason}" for reason in reasons]
        lines.append("■ 実行するとどうなるか")
        lines += [f"  - {line}" for line in impact_lines(call)]
        if traj is not None:
            names = sorted({c.name for s in traj.steps for c in s.calls if c.name != call.name})
            lines.append("■ ここまでに参照した情報（根拠）")
            lines += [f"  - {n}" for n in (names or ["（まだ何も参照していません）"])]
        if request:
            lines.append(f"■ 期限: {request['expires_at']}（{self.ttl_hours} 時間）")
        return "\n".join(lines)

    # -- 保存と読み込み -----------------------------------------------------
    @property
    def path(self) -> Path:
        return self.directory / f"{self.task_id}.json"

    def save(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": self.task_id, "threshold_yen": self.threshold_yen,
                   "ttl_hours": self.ttl_hours, "decisions": self.decisions,
                   "requests": self.requests, "signoffs": self.signoffs,
                   "replacements": self.replacements,
                   "reject_reasons": self.reject_reasons}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(self.path)  # 部分書き込みを読ませない（セッション6と同じ作法）
        return self.path

    @classmethod
    def load(cls, task_id: str, *, clock=None, directory: Path | None = None,
             audit: AuditLog | None = None) -> "ReviewGate":
        directory = Path(directory) if directory else GATE_DIR
        path = directory / f"{task_id}.json"
        if not path.exists():
            return cls(task_id, clock=clock, directory=directory, audit=audit)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(task_id, clock=clock, directory=directory, audit=audit,
                   threshold_yen=data.get("threshold_yen", THRESHOLD_YEN),
                   ttl_hours=data.get("ttl_hours", TTL_HOURS),
                   decisions=data.get("decisions"), requests=data.get("requests"),
                   signoffs=data.get("signoffs"), replacements=data.get("replacements"),
                   reject_reasons=data.get("reject_reasons"))
