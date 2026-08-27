#!/usr/bin/env python3
"""セッション7：短期メモリを介して走る実行器（圧縮方式を差し替えられる）。

セッション3の `ReActAgent` との違いは1点だけである。
**会話履歴を軌跡から丸ごと組み立て直すのではなく、短期メモリを経由させる。**

  - ツール結果は記録（33文字の固定幅）に正規化してメモリに入れる
  - 行動の前に「溢れているか」を判定する（停止条件はセッション3と同じ順序）
  - 溢れていたら圧縮方式を適用する。`none` なら打ち切る（stop_reason=budget）
  - `externalize` は溢れる前に外へ出す（長期メモリに保存し、参照だけ残す）

`agentkit` は1行も変更していない。

    python src/session07/runner.py                 # 圧縮なし（溢れて止まる）
    python src/session07/runner.py keep            # 選択的保持（完走する）
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.clock import FixedClock  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.memory import ShortTermMemory  # noqa: E402
from agentkit.models import Step, ToolCall, Trajectory  # noqa: E402
from bigtools import build_registry07  # noqa: E402
from compress import MIN_GROUP, POLICY_LABELS, apply_policy  # noqa: E402
from longterm import AuditMemory  # noqa: E402
from records import (body_of, constraints, kind_of, record,  # noqa: E402
                     retention, to_records, tokens)
from scenarios import AUDIT, INSTRUCTION, TASK  # noqa: E402

# 教材向けに縮めた上限。実モデルの上限（20万トークン規模）を 1,980 に置き換える。
# 記録1件＝近似11トークンなので、ちょうど 180 記録でいっぱいになる
MAX_CONTEXT = 1_980

# 制約の本文から「どの判定規則が有効か」を読み取るための対応
RULES = (("amount", "5万円以上"), ("deadline", "10日以内"),
         ("note", "注記"), ("cap", "上限"))
RULE_LABELS = {"amount": "金額", "deadline": "期限", "note": "注記", "cap": "件数上限"}
AMOUNT_THRESHOLD = 50_000
DEADLINE_DAYS = 10


# ---------------------------------------------------------------------------
# 判定と成果物（メモリに残っている記録だけから組み立てる）
# ---------------------------------------------------------------------------
def active_rules(records: list[str]) -> list[str]:
    """メモリに残っている制約から、いま有効な判定規則を求める。

    **制約が落ちれば規則が消える。** 圧縮の失敗が結論に直結する仕組みを、
    わざと分かる形にしてある。
    """
    found: list[str] = []
    bodies = [body_of(r) for r in constraints(records)]
    for name, needle in RULES:
        if any(needle in b for b in bodies):
            found.append(name)
    return found


def expense_rows(records: list[str]) -> list[dict]:
    """一覧の記録を判定に使える形に戻す。"""
    rows = []
    for r in records:
        if kind_of(r) != "一覧":
            continue
        parts = body_of(r).split()
        if len(parts) < 4 or not parts[1].isdigit():
            continue
        rows.append({"id": parts[0], "amount": int(parts[1]), "status": parts[2],
                     "date": parts[3], "note": "注記" in parts[4:]})
    return rows


def judge(records: list[str], clock=None) -> list[tuple[str, list[str]]]:
    """有効な規則で申請を突き合わせ、指摘を返す。"""
    clock = clock or FixedClock()
    today = clock.today()
    rules = active_rules(records)
    findings: list[tuple[str, list[str]]] = []
    for row in expense_rows(records):
        reasons: list[str] = []
        if ("amount" in rules and row["amount"] >= AMOUNT_THRESHOLD
                and row["status"] == "申請中"):
            reasons.append("金額")
        if "deadline" in rules and row["status"] == "申請中":
            started = date.fromisoformat(f"{today[:4]}-{row['date']}")
            if (date.fromisoformat(today) - started).days > DEADLINE_DAYS:
                reasons.append("期限")
        if "note" in rules and row["note"]:
            reasons.append("注記")
        if reasons:
            findings.append((row["id"], reasons))
    return sorted(findings)


def render_report(records: list[str], clock=None) -> str:
    """レポート本文をメモリから組み立てる（モデルの文章に依存させない）。"""
    clock = clock or FixedClock()
    rules = active_rules(records)
    findings = judge(records, clock)
    lines = ["# 経費監査レポート（TASK-007）",
             f"基準日: {clock.today()}",
             "適用した制約: " + (" / ".join(RULE_LABELS[r] for r in rules) or "なし"),
             f"指摘: {len(findings)} 件"]
    for eid, reasons in findings:
        lines.append(f"- {eid} ← {' / '.join(reasons)}")
    if not findings:
        lines.append("- （判定に使える制約がメモリに残っていません）")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
class MemoryRunner:
    """短期メモリを経由して走るエージェント。圧縮方式を差し替えて比べる。"""

    def __init__(self, llm, tools, *, policy: str = "none",
                 max_context_tokens: int = MAX_CONTEXT, task_id: str = "TASK-007",
                 max_steps: int = 10, clock=None, longterm: AuditMemory | None = None,
                 externalize_min: int = MIN_GROUP) -> None:
        self.llm = llm
        self.tools = tools
        self.specs = tools.specs()
        self.policy = policy
        self.task_id = task_id
        self.max_steps = max_steps
        self.clock = clock or FixedClock()
        self.longterm = longterm
        self.externalize_min = externalize_min
        self.memory = ShortTermMemory(
            items=[record(kind, body) for kind, body in INSTRUCTION],
            max_tokens=max_context_tokens)
        self.first_seen = list(self.memory.items)   # 一度でもメモリに入った記録
        self.compressions = 0
        self.lost_constraints: list[str] = []

    # -- 走行 ---------------------------------------------------------------
    def run(self, task: str = TASK) -> Trajectory:
        traj = Trajectory(task_id=self.task_id, task=task)
        while True:
            # ① 停止条件は行動の前に判定する（セッション3と同じ順序）
            if len(traj.steps) >= self.max_steps:
                traj.stop_reason = "max_steps"
                traj.final = f"上限 {self.max_steps} 手に達したので打ち切りました。"
                return traj

            # ② 溢れているか。圧縮するのはここだけ
            compressed = False
            if self.memory.overflowing():
                over = (f"記録{len(self.memory.items)} / "
                        f"近似{self.memory.total_tokens()} > 上限{self.memory.max_tokens}")
                if self.policy in ("none", "externalize"):
                    traj.stop_reason = "budget"
                    traj.final = (f"コンテキスト上限を超えました（{over}）。"
                                  f"圧縮方式 {self.policy} では続行できません。")
                    return traj
                before = list(self.memory.items)
                self.memory = apply_policy(self.policy, self.memory)
                self.compressions += 1
                compressed = True
                self.lost_constraints += retention(before, self.memory.items)["落ちた制約"]
                if self.memory.overflowing():
                    traj.stop_reason = "budget"
                    traj.final = f"圧縮しても収まりませんでした（{over}）。"
                    return traj

            sent = len(self.memory.items)

            # ③ 思考
            try:
                res = self.llm.respond(self._messages(task), self.specs)
            except Exception as exc:  # noqa: BLE001
                traj.stop_reason = "error"
                traj.final = f"LLM 呼び出しに失敗しました: {type(exc).__name__}: {exc}"
                return traj

            step = Step(index=len(traj.steps), thought=res.thought,
                        usage={"input_tokens": res.input_tokens,
                               "output_tokens": res.output_tokens, "llm": 1,
                               "policy": self.policy, "records": sent,
                               "memory_tokens": tokens(self.memory.items),
                               "compressed": compressed, "added": 0})
            self.add_record(record("思考", res.thought))

            # ④ 行動
            if not res.calls:
                traj.steps.append(step)
                if res.final is None:
                    continue                    # 思考だけのステップ（計画など）
                traj.final = res.final
                traj.stop_reason = "done"
                return traj

            added = 0
            for call in res.calls:
                rewritten = self._rewrite(call)
                step.calls.append(rewritten)
                result = self.tools.call(rewritten)
                step.results.append(result)
                if result.ok:
                    added += self._store(rewritten, result.content)
            step.usage["added"] = added
            traj.steps.append(step)

    # -- メモリの出し入れ ---------------------------------------------------
    def _messages(self, task: str) -> list[dict]:
        """会話履歴はメモリから作る。毎回作り直すのはセッション3・6と同じ考え方。"""
        return [{"role": "system", "content": "これまでの記録:\n" + self.memory.render()},
                {"role": "user", "content": task}]

    def add_record(self, rec: str) -> None:
        """記録を短期メモリに入れる。「一度は入った」記録も別に残す（保持率の分母）。"""
        self.memory.add(rec)
        self.first_seen.append(rec)

    def _store(self, call: ToolCall, content: str) -> int:
        """ツール結果をメモリに入れる。外部化のときだけ外に出す。"""
        recs = to_records(content)
        if self.policy != "externalize" or len(recs) < self.externalize_min:
            for rec in recs:
                self.add_record(rec)
            return len(recs)
        # 大きな結果は長期メモリへ。短期に残すのは参照1件と、中にあった制約だけ
        if self.longterm is None:
            self.longterm = AuditMemory("session07", clock=self.clock)
        label = str(call.args.get("month") or call.args.get("status") or call.name)
        key = f"{call.name}:{label}"
        self.longterm.remember(key, content, kind="tool_result", importance=2,
                               source=f"{call.name} の結果")
        tag = label[5:7] if label[:2] == "20" else label   # "2026-07" → "07"
        kept = [record("参照", f"{tag}のログ{len(recs)}行を長期メモリに保存。")]
        kept += [r for r in recs if kind_of(r) == "制約"]
        for rec in kept:
            self.add_record(rec)
        return len(kept)

    def _rewrite(self, call: ToolCall) -> ToolCall:
        """レポート本文と保存先を、モデルの提案から差し替える。"""
        if call.name != "write_audit_report":
            return call
        args = dict(call.args)
        args["path"] = f"session07/audit_{self.policy}.md"
        if args.get("content") == "__REPORT__":
            args["content"] = render_report(self.memory.items, self.clock)
        return ToolCall(call.call_id, call.name, args)

    # -- 観測 ---------------------------------------------------------------
    def result(self, traj: Trajectory) -> dict:
        """比較表の1行ぶん。圧縮方式ごとの「収まり方」と「成果」を並べる。"""
        info = retention(self.first_seen, self.memory.items)
        findings = judge(self.memory.items, self.clock)
        return {"方式": POLICY_LABELS[self.policy], "手数": len(traj.steps),
                "最終記録数": len(self.memory.items),
                "近似トークン": self.memory.total_tokens(),
                "制約": f"{info['残った制約']}/{info['制約の総数']}",
                "指摘": len(findings),
                "停止理由": traj.stop_reason, "圧縮回数": self.compressions}


def render_run(traj: Trajectory) -> str:
    """1行1ステップで「メモリの大きさ」と「何をしたか」を表示する。"""
    policy = traj.steps[0].usage.get("policy", "?") if traj.steps else "?"
    lines = [f"task_id={traj.task_id} policy={policy} "
             f"stop_reason={traj.stop_reason} 手数={len(traj.steps)}"]
    for s in traj.steps:
        u = s.usage
        mark = " [圧縮]" if u.get("compressed") else ""
        if s.calls:
            action = " ".join(f"{c.name}:{'ok' if r.ok else 'NG'}"
                              for c, r in zip(s.calls, s.results))
            action += f" +{u.get('added', 0)}"
        else:
            action = "（ツールなし）"
        lines.append(f"  step {s.index} 記録={u.get('records')} "
                     f"近似={u.get('memory_tokens')}{mark} {action}")
    lines.append(f"  final: {traj.final}")
    return "\n".join(lines)


def build(policy: str = "none", scenario=None, **kwargs) -> MemoryRunner:
    return MemoryRunner(ScriptedClient(scenario or AUDIT), build_registry07(),
                        policy=policy, **kwargs)


def run_policies(policies=("none", "truncate", "summarize", "keep",
                           "externalize", "summarize_all")) -> list[dict]:
    """方式ごとに同じタスクを走らせ、比較表の行を返す（決定的）。"""
    rows = []
    for policy in policies:
        memory = AuditMemory(f"session07_{policy}")
        memory.clear()
        runner = build(policy, longterm=memory)
        rows.append(runner.result(runner.run()))
    return rows


if __name__ == "__main__":
    policy = sys.argv[1] if len(sys.argv) > 1 else "none"
    memory = AuditMemory(f"session07_{policy}")
    memory.clear()
    runner = build(policy, longterm=memory)
    traj = runner.run()
    print(render_run(traj))
    print()
    print(runner.result(traj))
