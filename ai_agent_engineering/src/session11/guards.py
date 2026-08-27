#!/usr/bin/env python3
"""循環検出・上限・引き継ぎ書（セッション11）。

エージェントが自分で止まれない典型は2つある。

  1. 同じ行動を繰り返す（同じツール・同じ引数）
  2. 少しずつ違う行動を無限に続ける（上限に達するまで止まらない）

1 は検出できる。2 は検出できないので上限で殺す。どちらの場合も、止めたあとに
**人が何を受け取るか**まで設計して初めて「打ち切れた」と言える。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import ToolCall, Trajectory  # noqa: E402
from failure_kinds import PARTIAL, classify_error  # noqa: E402


# --- 循環検出 ---------------------------------------------------------------
def call_key(call: ToolCall) -> str:
    """「同じ行動」の定義。ツール名だけでなく引数まで含める。

    引数を含めないと、会議室を別の時間帯で探し直す正常な動きまで循環に見える。
    """
    return f"{call.name}:{json.dumps(call.args, ensure_ascii=False, sort_keys=True)}"


def detect_repeat(keys: list[str], window: int = 3) -> bool:
    """同じキーが window 回連続したら循環と見なす。"""
    if window < 2 or len(keys) < window:
        return False
    return len(set(keys[-window:])) == 1


def detect_alternating(keys: list[str], cycle: int = 2, times: int = 2) -> bool:
    """A,B,A,B のように cycle 個の並びが times 回繰り返したら循環と見なす。

    「同じ操作の連続」だけを見ていると、2つの操作を交互に試し続ける行き詰まり
    （みなと10:00 → 大会議室13:00 → みなと10:00 …）を見逃す。
    """
    need = cycle * times
    if cycle < 2 or times < 2 or len(keys) < need:
        return False
    tail = keys[-need:]
    head = tail[:cycle]
    if len(set(head)) < 2:
        return False   # 同じキーの並びは detect_repeat の担当
    return all(tail[i * cycle:(i + 1) * cycle] == head for i in range(times))


def detect_loop(keys: list[str], *, window: int = 3, alternating: bool = True) -> bool:
    if not window:
        return False   # window=0 で循環検出そのものを切る
    if detect_repeat(keys, window=window):
        return True
    return bool(alternating) and detect_alternating(keys)


def brief_call(call: ToolCall, limit: int = 24) -> str:
    """人に見せる用の短い表記。長い引数は切り詰める。

    引き継ぎ書に JSON をそのまま貼ると読まれない。読まれない引き継ぎ書は
    書いていないのと同じである。
    """
    parts = []
    for k in sorted(call.args):
        v = str(call.args[k]).replace("\n", " ")
        parts.append(f"{k}={v[:limit]}{'…' if len(v) > limit else ''}")
    return f"{call.name}({', '.join(parts)})"


# --- 上限 -------------------------------------------------------------------
LIMIT_LABELS = {"max_steps": "ステップ数", "max_tool_calls": "ツール呼び出し回数",
                "max_input_tokens": "入力トークン（近似）", "deadline_seconds": "経過時間"}
LIMIT_UNITS = {"max_steps": "ステップ", "max_tool_calls": "回",
               "max_input_tokens": "トークン", "deadline_seconds": "秒"}


@dataclass
class RunLimits:
    """1回の実行に許す上限。**達したら止める**（超えてからではない）。

    `agentkit.loop.Budget` は「超えたら止める」（`>`）ので、上限を1つ踏み越えた
    ところで止まる。金額や送信のように1回が重い操作では、踏み越えた1回が
    そのまま事故になる。この章では `>=` にしておく。
    """

    max_steps: int = 8
    max_tool_calls: int = 12
    max_input_tokens: int = 50_000
    deadline_seconds: int = 600

    def reached(self, traj: Trajectory, *, elapsed: float = 0.0) -> str | None:
        """達した上限の名前を返す。達していなければ None。"""
        if len(traj.steps) >= self.max_steps:
            return "max_steps"
        if len(traj.tool_names) >= self.max_tool_calls:
            return "max_tool_calls"
        if traj.total_tokens["input"] >= self.max_input_tokens:
            return "max_input_tokens"
        if elapsed >= self.deadline_seconds:
            return "deadline_seconds"
        return None

    def text(self, hit: str) -> str:
        return f"{LIMIT_LABELS[hit]} {getattr(self, hit)}{LIMIT_UNITS[hit]}"


# --- 失敗の伝え方 -----------------------------------------------------------
def side_effects(traj: Trajectory, tools=None) -> list[str]:
    """成功した書き込み系の操作（＝取り消していない副作用）を並べる。"""
    out: list[str] = []
    for step in traj.steps:
        for call, result in zip(step.calls, step.results):
            tool = tools.get(call.name) if tools is not None else None
            if tool is not None and "write" not in tool.tags:
                continue
            if result.ok:
                out.append(brief_call(call))
    return out


def uncertain_effects(traj: Trajectory) -> list[str]:
    """実行されたかどうか分からない操作を並べる（部分的失敗）。

    引き継ぎ書でいちばん大事な欄。ここが空でないなら、人は**まず照合する**。
    """
    out: list[str] = []
    for step in traj.steps:
        for call, result in zip(step.calls, step.results):
            if not result.ok and classify_error(result.error or "") == PARTIAL:
                out.append(brief_call(call))
    return out


def handoff_report(traj: Trajectory, tools=None, *, reason: str) -> str:
    """人に渡す引き継ぎ書。5項目を必ず埋める。"""
    unsure = uncertain_effects(traj)
    done = side_effects(traj, tools)
    if unsure:
        nxt = ("外部の記録（data/ のファイル）を照合し、実行済みなら再実行しないでください。"
               "照合には冪等キーを使います。")
    elif done:
        nxt = "済んだ操作を活かして続きから実行するか、補償して元に戻してください。"
    else:
        nxt = "副作用は出ていません。条件を見直して最初からやり直せます。"
    return "\n".join([
        "人に引き継ぎます。次の5点を確認してください。",
        f"- 頼まれたこと: {traj.task or '（記録なし）'}",
        f"- 止まった理由: {reason}",
        f"- 済んでいて取り消していない操作: {', '.join(done) if done else 'なし'}",
        f"- 実行されたか分からない操作: {', '.join(unsure) if unsure else 'なし'}",
        f"- 次にやること: {nxt}",
    ])


def render_limit_final(on_limit: str, hit: str, traj: Trajectory,
                       limits: RunLimits, tools=None) -> str:
    """上限に達したときに返す文面（セッション3の on_limit の3種類）。"""
    what = limits.text(hit)
    if on_limit == "fail":
        return f"上限（{what}）に達したため中止しました。完了していません。"
    if on_limit == "partial":
        done = [c.name for s in traj.steps for c, r in zip(s.calls, s.results) if r.ok]
        last = ""
        for step in reversed(traj.steps):
            for result in reversed(step.results):
                if result.ok and result.content:
                    last = result.content.replace("\n", " ")[:60]
                    break
            if last:
                break
        return "\n".join([
            f"上限（{what}）に達したので、ここまでの結果を返します。"
            "これは完了した回答ではありません。",
            f"- 済んだ操作: {', '.join(done) if done else 'なし'}",
            f"- 直近に得られた情報: {last or 'なし'}",
        ])
    if on_limit == "handoff":
        return handoff_report(traj, tools, reason=f"上限に達した（{what}）")
    raise ValueError(f"on_limit は fail / partial / handoff です: {on_limit!r}")


if __name__ == "__main__":
    same = ["book_room:A", "book_room:A", "book_room:A"]
    alt = ["book_room:A", "book_room:B", "book_room:A", "book_room:B"]
    ok = ["get_policy:X", "list_expenses:Y", "write_file:Z"]
    for label, keys in (("同じ引数の連続", same), ("交互の繰り返し", alt),
                        ("正常な3手", ok)):
        print(f"{label}: 連続={detect_repeat(keys)} 交互={detect_alternating(keys)} "
              f"判定={detect_loop(keys)}")
