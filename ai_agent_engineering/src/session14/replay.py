#!/usr/bin/env python3
"""セッション14：再生 — 記録から同じ失敗をローカルで起こす。

    python src/session14/replay.py

再生の仕組みは単純である。「そのときのプロンプト」をキーにして「そのときの応答」を
返すだけ。難しいのは**プロンプトを1バイトも変えずに作り直せるか**という一点に尽きる。

  - プロンプトは会話履歴から作られる（`ReActAgent._rebuild_messages` と同じ手順）
  - 会話履歴には `call_id`・ツール結果の本文がそのまま入る
  - つまり **`call_id` かツール結果を1文字でも変えると、キーが外れて再生が止まる**

`agentkit.llm.FixtureClient` は `call_id` を `fx-...` に作り直すため、2手目でキーが
外れる。本モジュールはそれを実演したうえで、`call_id` を記録どおりに返す薄い
クライアント（`ReplayClient`）を足す。`agentkit` は1行も変更しない。
"""

from __future__ import annotations

import json
from pathlib import Path

from spanlog import ROOT, Trajectory, reset_data, run_case  # noqa: E402

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import FixtureClient, prompt_key  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import LLMResponse, ToolCall  # noqa: E402

FIXTURE_DIR = ROOT / "fixtures"


# ---------------------------------------------------------------------------
# プロンプトの作り直し（`ReActAgent._rebuild_messages` と同じ手順）
# ---------------------------------------------------------------------------
def rebuild_messages(task: str, steps: list, system: str = "") -> list[dict]:
    """軌跡の先頭 N ステップから、その時点の会話履歴を作り直す。

    **記録に何が要るか**がここで決まる。`call_id`・ツール名・引数・結果の本文・
    成否の5つが揃っていないと、同じ履歴は作れない（＝再生できない）。
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": task})
    for s in steps:
        if s.calls:
            messages.append({
                "role": "assistant",
                "content": ([{"type": "text", "text": s.thought}] if s.thought else [])
                + [{"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.args}
                   for c in s.calls],
            })
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": r.call_id,
                             "content": r.content if r.ok else (r.error or ""),
                             "is_error": not r.ok}
                            for r in s.results],
            })
    return messages


def make_cassette(task: str, traj: Trajectory, specs: list[dict], system: str = "") -> dict:
    """軌跡からカセット（プロンプトのハッシュ → 応答）を作る。"""
    cassette: dict[str, dict] = {}
    for i, step in enumerate(traj.steps):
        key = prompt_key(rebuild_messages(task, traj.steps[:i], system), specs)
        cassette[key] = {
            "thought": step.thought,
            "calls": [{"call_id": c.call_id, "name": c.name, "args": dict(c.args)}
                      for c in step.calls],
            "final": traj.final if not step.calls else None,
            "input_tokens": step.usage.get("input_tokens", 0),
            "output_tokens": step.usage.get("output_tokens", 0),
        }
    return cassette


def save_cassette(name: str, cassette: dict) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(json.dumps(cassette, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 再生クライアント
# ---------------------------------------------------------------------------
class ReplayClient:
    """記録した応答を、**記録した `call_id` のまま**返す。

    `FixtureClient` との違いはここだけである。ID を作り直さないので、
    2手目以降のプロンプトが記録時と1バイトも変わらない。
    """

    def __init__(self, cassette: dict) -> None:
        self.cassette = cassette
        self.hits = 0
        self.misses: list[str] = []

    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        key = prompt_key(messages, tools)
        row = self.cassette.get(key)
        if row is None:
            self.misses.append(key)
            raise KeyError(
                f"記録に無いプロンプトです（key={key}）。"
                "再生は、記録した通りの入力でしか成立しません。"
            )
        self.hits += 1
        return LLMResponse(
            thought=row.get("thought", ""),
            calls=[ToolCall(c["call_id"], c["name"], c.get("args", {}))
                   for c in row.get("calls", [])],
            final=row.get("final"),
            input_tokens=row.get("input_tokens", 0),
            output_tokens=row.get("output_tokens", 0),
            source="replay",
        )


def replay_with_recorded_ids(task: str, cassette: dict, *, tools=None, max_steps: int = 8,
                             task_id: str = "TASK-replay") -> Trajectory:
    agent = ReActAgent(ReplayClient(cassette), tools or build_registry(), max_steps=max_steps)
    return agent.run(task, task_id=task_id)


def replay_with_fixture(task: str, name: str, *, tools=None, max_steps: int = 8,
                        task_id: str = "TASK-replay") -> Trajectory:
    agent = ReActAgent(FixtureClient(name), tools or build_registry(), max_steps=max_steps)
    return agent.run(task, task_id=task_id)


def exception_name(traj: Trajectory) -> str:
    """`stop_reason == "error"` のときに、何の例外で止まったかを取り出す。"""
    if traj.stop_reason != "error" or not traj.final:
        return "—"
    parts = traj.final.split(": ")
    return parts[1] if len(parts) > 1 else "—"


def same_trajectory(a: Trajectory, b: Trajectory) -> dict:
    """再生できたかの判定。**`call_id` ではなくツール列と結果で比べる**。"""
    return {
        "tools": a.tool_names == b.tool_names,
        "steps": len(a.steps) == len(b.steps),
        "stop_reason": a.stop_reason == b.stop_reason,
        "final": (a.final or "") == (b.final or ""),
        "tokens": a.total_tokens == b.total_tokens,
    }


# ---------------------------------------------------------------------------
def main() -> None:
    reset_data()
    task, scenario, max_steps = "同じ検索を繰り返す", "max_steps_loop", 6

    print("=== ①記録する（失敗した1件）===")
    original = run_case(scenario, task, max_steps)
    specs = build_registry().specs()
    cassette = make_cassette(task, original, specs)
    path = save_cassette("s14_max_steps_loop", cassette)
    print(f"{original.task_id}: 手数={len(original.steps)} 停止理由={original.stop_reason} "
          f"ツール呼び出し={len(original.tool_names)}")
    print(f"カセット: {path.relative_to(ROOT)}（{len(cassette)} 件のプロンプト→応答）")

    print("\n=== ②FixtureClient で再生する ===")
    fixture = replay_with_fixture(task, "s14_max_steps_loop", max_steps=max_steps)
    print(f"手数={len(fixture.steps)} 停止理由={fixture.stop_reason} "
          f"例外={exception_name(fixture)}")
    print("→ 1手目は再現したが、2手目で止まった。FixtureClient は call_id を "
          "fx-... に作り直すため、2手目のプロンプトが記録時と変わってキーが外れる。")

    print("\n=== ③記録した call_id のまま再生する（ReplayClient）===")
    replayed = replay_with_recorded_ids(task, cassette, max_steps=max_steps)
    flags = same_trajectory(original, replayed)
    labels = {"tools": "ツール列", "steps": "手数", "stop_reason": "停止理由",
              "final": "最終回答", "tokens": "近似トークン"}
    print(f"手数={len(replayed.steps)} 停止理由={replayed.stop_reason} "
          + " ".join(f"{labels[k]}一致={v}" for k, v in flags.items()))
    print("→ 同じ失敗がローカルで再現した。原因のステップを何度でも観察できる。")

    print("\n=== ④記録した通りの入力でしか再生できない ===")
    changed = replay_with_recorded_ids(task + "。", cassette, max_steps=max_steps)
    print(f"依頼文の末尾に1文字足す → 手数={len(changed.steps)} "
          f"停止理由={changed.stop_reason} 例外={exception_name(changed)}")
    print("→ プロンプトが変われば別のキーになる。再生はデバッグの道具であって、"
          "モデルの代わりではない。")

    reset_data()


if __name__ == "__main__":
    main()
