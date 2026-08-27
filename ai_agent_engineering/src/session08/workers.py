#!/usr/bin/env python3
"""セッション8：ワーカー（1体のエージェント）と、引き継ぎ情報の梱包・開封。

この章で足りないものは3つで、どれも `agentkit` の外側で足せる。

  1. 役割ごとにツールを絞る      → `ToolRegistry.subset()` を包む（最小権限）
  2. 引き継ぎ情報をプロンプトに載せる → `format_handoff` / `parse_handoff`
  3. 呼び出しの重さを数える        → `CountingClient` で LLM を包む

**受け取る側にとって、プロンプトに書かれていない情報は存在しない。**
この1点が、複数体構成のほぼすべての事故の原因である。
"""

from __future__ import annotations

import json
import re
import sys
import threading
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.clock import FixedClock  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import Trajectory  # noqa: E402
from agentkit.tools import ToolRegistry  # noqa: E402
from report import (EXPENSE_FIELDS, analyze, derived, extract_threshold,  # noqa: E402
                    parse_expense_table, render_notice, render_report)

HANDOFF_HEADER = "# 引き継ぎ情報"

# 役割ごとに使ってよいツール。**分割はそのまま最小権限になる**（セッション12へ続く）
ROLE_TOOLS = {
    "solo": ["get_policy", "list_expenses", "write_file", "send_message"],
    "collector": ["get_policy", "list_expenses"],
    "policy_collector": ["get_policy"],
    "expense_collector": ["list_expenses"],
    "analyst": [],                      # 計算だけの役。ツールを持たない
    "writer": ["write_file"],
    "notifier": ["send_message"],
}

# その役が「作れる」事実（＝渡せる情報の上限）
PRODUCES = {
    "collector": ("expenses", "threshold", "policy_digest"),
    "policy_collector": ("threshold", "policy_digest"),
    "expense_collector": ("expenses",),
    "analyst": ("by_category", "total", "count", "violations"),
    "writer": ("report_path",),
    "notifier": (),
}

# その役が「必要とする」事実（＝渡し手が満たすべき契約）
NEEDS = {
    "analyst": ("expenses", "threshold"),
    "writer": ("by_category", "total", "count", "violations", "threshold"),
    "notifier": ("report_path", "total", "violations_count"),
}

JSON_KEYS = ("expenses", "by_category", "violations")
INT_KEYS = ("threshold", "total", "count", "violations_count")


# ---------------------------------------------------------------------------
# 引き継ぎ情報の梱包と開封
# ---------------------------------------------------------------------------
def encode(key: str, value) -> str:
    """1行に収まる文字列にする。改行を含めない（受け取り側は行で読む）。"""
    if key == "expenses":
        # 判断に使う列だけを渡す。渡す量も設計対象である
        return json.dumps([{k: r[k] for k in EXPENSE_FIELDS} for r in value],
                          ensure_ascii=False)
    if key in JSON_KEYS:
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def pack(keys, facts: dict) -> dict[str, str]:
    """指定した鍵だけを取り出して梱包する。持っていない鍵は入らない（落ちる）。"""
    out: dict[str, str] = {}
    for key in keys:
        if key == "violations_count":
            if isinstance(facts.get("violations"), list):
                out[key] = str(len(facts["violations"]))
            elif isinstance(facts.get("violations_count"), int):
                out[key] = str(facts["violations_count"])
            continue
        value = facts.get(key)
        if value is not None:
            out[key] = encode(key, value)
    return out


def format_handoff(task: str, context: dict[str, str]) -> str:
    """タスク文の後ろに引き継ぎ情報を足す。

    形は `agentkit.multi.Orchestrator.run_sequence` と同じにしてある
    （`- 鍵: 値` を1行ずつ）。**プロンプトに入った分だけが相手に届く**。
    """
    if not context:
        return task
    body = "\n".join(f"- {k}: {v}" for k, v in context.items())
    return f"{task}\n\n{HANDOFF_HEADER}\n{body}"


def parse_handoff(task: str) -> dict[str, str]:
    """タスク文に埋め込まれた引き継ぎ情報を辞書に戻す。"""
    if HANDOFF_HEADER not in task:
        return {}
    block = task.split(HANDOFF_HEADER, 1)[1]
    out: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("- ") or ": " not in line:
            continue
        key, value = line[2:].split(": ", 1)
        out[key.strip()] = value.strip()
    return out


def from_free_text(text: str) -> dict:
    """自由文から数値を拾い直す。**壊れやすい経路**（伝言ゲームの現場）。

    書き手が言い方を変えれば拾えなくなる。構造化して渡せばこの関数は不要になる。
    """
    out: dict = {}
    m = re.search(r"合計は?\s*([\d,]+)\s*円", text)
    if m:
        out["total"] = int(m.group(1).replace(",", ""))
    m = re.search(r"([\d,]+)\s*件", text)
    if m:
        out["count"] = int(m.group(1).replace(",", ""))
    m = re.search(r"([\w./-]+\.md)", text)
    if m:
        out["report_path"] = m.group(1)
    return out


def decode_facts(raw: dict[str, str]) -> dict:
    """開封する。型を戻し、壊れて届いた項目は None（＝未取得）にする。"""
    facts: dict = {}
    for key, value in raw.items():
        if key in JSON_KEYS:
            try:
                facts[key] = json.loads(value)
            except json.JSONDecodeError:
                facts[key] = None
        elif key in INT_KEYS:
            try:
                facts[key] = int(value)
            except ValueError:
                facts[key] = None
        else:
            facts[key] = value
    if raw.get("previous_result"):
        facts.update(from_free_text(raw["previous_result"]))
    return facts


# ---------------------------------------------------------------------------
# 計測（外側から包んで数える）
# ---------------------------------------------------------------------------
class Ledger:
    """呼び出しの重さを役割ごとに数える台帳。

    近似トークン数は「メッセージの文字数÷3」の**比較用**の値である（実 API の
    計測値ではない）。`ScriptedClient` はメッセージだけを数えており、
    **ツール定義は含まない**。そこでツール定義は別の数として数える。
    """

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.specs_sent: dict[str, int] = {}
        self.results_in_context: dict[str, int] = {}
        self.approx_in: dict[str, list[int]] = {}
        self.hops: list[dict] = []
        self._lock = threading.Lock()

    def record_call(self, agent: str, messages: list[dict], tools: list[dict]) -> None:
        results = sum(1 for m in messages
                      if isinstance(m.get("content"), list)
                      for b in m["content"]
                      if isinstance(b, dict) and b.get("type") == "tool_result")
        approx = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 3
        with self._lock:  # 並列に走らせても集計が壊れないようにする
            self.calls[agent] = self.calls.get(agent, 0) + 1
            self.specs_sent[agent] = self.specs_sent.get(agent, 0) + len(tools)
            self.results_in_context[agent] = self.results_in_context.get(agent, 0) + results
            self.approx_in.setdefault(agent, []).append(approx)

    def record_hop(self, frm: str, to: str, context: dict[str, str]) -> None:
        with self._lock:
            self.hops.append({"from": frm, "to": to, "keys": sorted(context),
                              "fields": len(context),
                              "chars": sum(len(v) for v in context.values())})

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    @property
    def total_specs(self) -> int:
        return sum(self.specs_sent.values())

    @property
    def total_results(self) -> int:
        return sum(self.results_in_context.values())

    @property
    def total_hop_fields(self) -> int:
        return sum(h["fields"] for h in self.hops)

    @property
    def total_hop_chars(self) -> int:
        return sum(h["chars"] for h in self.hops)

    @property
    def total_in(self) -> int:
        return sum(sum(v) for v in self.approx_in.values())

    @property
    def max_in(self) -> int:
        return max((max(v) for v in self.approx_in.values() if v), default=0)


class CountingClient:
    """LLM を包んで呼び出しの重さを数える。

    エージェント本体（`agentkit.loop.ReActAgent`）を変更せずに計測できる。
    **計測は外側から包む**のが原則である。
    """

    def __init__(self, inner, ledger: Ledger, agent: str) -> None:
        self.inner = inner
        self.ledger = ledger
        self.agent = agent

    def respond(self, messages: list[dict], tools: list[dict]):
        self.ledger.record_call(self.agent, messages, tools)
        return self.inner.respond(messages, tools)


# ---------------------------------------------------------------------------
# ツールを役割ぶんに絞り、事実の出入りを記録する
# ---------------------------------------------------------------------------
def wrap_tools(base: ToolRegistry, allow: list[str], facts: dict) -> ToolRegistry:
    """許可リストで絞ったうえで、ツールの入口と出口に処理を足す。

    - `subset()` で許可リストを作る（登録されていないツールは呼べない）
    - ツール結果から「次の判断に使う事実」を抜き出して facts に溜める
    - `__REPORT__` / `__NOTICE__` は「本文は事実から組み立てる」ための目印
      （セッション6と同じ。成果物をモデルの文章に依存させない）
    """
    allowed = base.subset(allow)
    return ToolRegistry([replace(allowed.get(name), fn=_instrument(allowed.get(name), facts))
                         for name in allowed.names()])


def _instrument(tool, facts: dict):
    original, name = tool.fn, tool.name

    def fn(**kwargs):
        if name == "write_file" and kwargs.get("content") == "__REPORT__":
            kwargs = {**kwargs, "content": render_report(facts)}
        if name == "send_message" and kwargs.get("body") == "__NOTICE__":
            kwargs = {**kwargs, "body": render_notice(facts)}
        content = original(**kwargs)
        if name == "list_expenses":
            facts["expenses"] = parse_expense_table(content)
        if name == "get_policy":
            facts["policy_digest"] = content
            threshold = extract_threshold(content)
            if threshold is not None:
                facts["threshold"] = threshold
        if name == "write_file":
            facts["report_path"] = kwargs.get("path")
        return content

    return fn


# ---------------------------------------------------------------------------
# ワーカー
# ---------------------------------------------------------------------------
class Worker:
    """1体のエージェント。役割ぶんのツールだけを持ち、事実を自分の中に溜める。

    `run(task, task_id=...)` を持つので `agentkit.multi.Orchestrator` に
    そのまま渡せる（ダックタイピング。親は中身を知らなくてよい）。
    """

    def __init__(self, role: str, scenario: dict, *, ledger: Ledger | None = None,
                 base: ToolRegistry | None = None, allow: list[str] | None = None,
                 max_steps: int = 6, analyze_after: bool = False) -> None:
        self.role = role
        self.ledger = ledger or Ledger()
        self.facts: dict = {}
        self.base = base or build_registry()
        self.allow = list(ROLE_TOOLS[role] if allow is None else allow)
        self.tools = wrap_tools(self.base, self.allow, self.facts)
        self.llm = CountingClient(ScriptedClient(scenario), self.ledger, role)
        self.agent = ReActAgent(self.llm, self.tools, max_steps=max_steps,
                                clock=FixedClock())
        self.analyze_after = analyze_after
        self.trajectory: Trajectory | None = None

    def run(self, task: str, task_id: str = "TASK-008") -> Trajectory:
        # 受け取れるのは、タスク文に書かれている分だけ（ここが伝言ゲームの境界）
        self.facts.update(decode_facts(parse_handoff(task)))
        traj = self.agent.run(task, task_id=task_id)
        if self.analyze_after:
            self.facts.update(analyze(self.facts))
        self.trajectory = traj
        return traj

    def publish(self, blackboard, keys=None) -> dict[str, str]:
        """自分が作った事実を黒板に書く。書いた分だけが他人から見える。"""
        produced = pack(PRODUCES.get(self.role, ()) if keys is None else keys, self.facts)
        for key, value in produced.items():
            blackboard.write(self.role, key, value)
        return produced

    def snapshot(self) -> dict:
        """いま持っている事実（導ける値も足したもの）。デバッグに使う。"""
        return derived(self.facts)
