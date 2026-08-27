#!/usr/bin/env python3
"""セッション8：同じ仕事を「単体 / オーケストレータ型 / ハンドオフ型」で走らせる。

3方式の違いは、コードの量ではなく**情報と権限の配り方**にある。

  単体            … 1体が全部のツールを持ち、全部の事実を1つの文脈に溜める
  オーケストレータ型 … 親が配って集める。事実は黒板（中央の記録）に残る
  ハンドオフ型      … 横に渡す。親はいない。渡す情報は送り手が決める

`agentkit.multi` の `Orchestrator` / `Handoff` / `Blackboard` をそのまま使い、
足りない部分（誰に何を渡すか）をこの層で決めている。
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.multi import Blackboard, Handoff, Orchestrator  # noqa: E402
from report import score  # noqa: E402
from scenarios import (ANALYST, COLLECTOR, EXPENSE_COLLECTOR,  # noqa: E402
                       NOTIFIER, POLICY_COLLECTOR, SOLO, WRITER)
from sideeffects import read_messages, read_report, reset_data  # noqa: E402
from workers import Ledger, NEEDS, PRODUCES, Worker, format_handoff, pack  # noqa: E402

TASK_MAIN = ("経費申請を区分ごとに集計し、規程に違反している申請を注記した月次レポートを "
             "session08/report.md に保存し、経理部へ完了を報告してください")

ROLE_TASKS = {
    "collector": "経費精算の規程と経費申請の一覧を集めてください",
    "policy_collector": "経費精算の規程を確認し、判定基準の金額を報告してください",
    "expense_collector": "経費申請の一覧を取得して報告してください",
    "analyst": "受け取った経費申請を区分ごとに集計し、基準額以上で未承認の申請を洗い出してください",
    "writer": "受け取った集計結果を月次レポートとして session08/report.md に保存してください",
    "notifier": "月次レポートの保存が完了したことを経理部へ報告してください",
}

SCENARIOS = {
    "collector": COLLECTOR, "analyst": ANALYST, "writer": WRITER, "notifier": NOTIFIER,
    "policy_collector": POLICY_COLLECTOR, "expense_collector": EXPENSE_COLLECTOR,
}


# ---------------------------------------------------------------------------
# 共通の後始末（採点と集計）
# ---------------------------------------------------------------------------
def count_stages(ledger: Ledger, layers: list[list[str]]) -> int:
    """段数＝直列に並ぶ LLM 呼び出しの段数。並列に走る分は最大値で数える。

    実時間を測ると環境で変わって再現しない。「何段またぐか」は決定的に数えられる
    レイテンシの代理指標である。
    """
    return sum(max(ledger.calls.get(role, 0) for role in layer) for layer in layers)


def finish(label: str, ledger: Ledger, trajectories: dict, layers: list[list[str]],
           blackboard: Blackboard | None = None) -> dict:
    report, notices = read_report(), read_messages()
    return {
        "方式": label,
        "ledger": ledger,
        "trajectories": trajectories,
        "blackboard": blackboard,
        "report": report,
        "notices": notices,
        "score": score(report, notices),
        "stages": count_stages(ledger, layers),
        "tool_calls": sum(len(t.tool_names) for t in trajectories.values()),
        "stop_reasons": {k: t.stop_reason for k, t in trajectories.items()},
    }


def build_workers(roles, ledger: Ledger) -> dict[str, Worker]:
    return {role: Worker(role, SCENARIOS[role], ledger=ledger,
                         analyze_after=(role == "analyst"))
            for role in roles}


# ---------------------------------------------------------------------------
# 1. 単体
# ---------------------------------------------------------------------------
def run_solo(ledger: Ledger | None = None) -> dict:
    """1体で最後まで走る。事実は1つの文脈に溜まるので、引き継ぎは1回も起きない。"""
    reset_data()
    ledger = ledger or Ledger()
    worker = Worker("solo", SOLO, ledger=ledger)
    traj = worker.run(TASK_MAIN, task_id="TASK-008")
    return finish("単体", ledger, {"solo": traj}, [["solo"]])


# ---------------------------------------------------------------------------
# 2. オーケストレータ型（親が配って集める）
# ---------------------------------------------------------------------------
def context_from_blackboard(blackboard: Blackboard, keys) -> dict[str, str]:
    """黒板から、次の相手が必要とする分だけを取り出す。

    `latest()` は「最後に書かれた値」を返す。複数体が同じ鍵に書くと
    先に書いた値は見えなくなる（`conflict.py` で扱う）。
    """
    out: dict[str, str] = {}
    for key in keys:
        if key == "violations_count":
            raw = blackboard.latest("violations")
            if raw is not None:
                out[key] = str(len(json.loads(raw)))
            continue
        value = blackboard.latest(key)
        if value is not None:
            out[key] = value
    return out


def run_orchestrator(mode: str = "structured", ledger: Ledger | None = None) -> dict:
    """親が順番に配る。`mode` は親が渡す情報の形。

    structured … 黒板から「次の相手が必要とする鍵」だけを渡す
    free       … 前段の最終回答（自由文）だけを渡す
                 ＝ `Orchestrator.run_sequence` の既定の振る舞いと同じ
    """
    if mode not in ("structured", "free"):
        raise ValueError(f"mode は structured か free です: {mode!r}")
    reset_data()
    ledger = ledger or Ledger()
    order = ["collector", "analyst", "writer", "notifier"]
    workers = build_workers(order, ledger)
    orch = Orchestrator(workers=workers, blackboard=Blackboard())

    for i, role in enumerate(order, start=1):
        if i == 1:
            context: dict[str, str] = {}
        elif mode == "free":
            previous = orch.blackboard.latest("result")
            context = {"previous_result": previous} if previous is not None else {}
        else:
            context = context_from_blackboard(orch.blackboard, NEEDS[role])
        if context:
            ledger.record_hop("親", role, context)
        orch.dispatch(role, format_handoff(ROLE_TASKS[role], context), f"TASK-008-{i:02d}")
        # ワーカーは自分が作った事実を黒板に書いて終わる（親はそれを配る）
        workers[role].publish(orch.blackboard)

    label = "オーケストレータ（構造化）" if mode == "structured" else "オーケストレータ（自由文）"
    return finish(label, ledger, orch.trajectories, [[r] for r in order], orch.blackboard)


def run_orchestrator_parallel(ledger: Ledger | None = None) -> dict:
    """独立した読み取り2件を同時に走らせる。段数は減り、総手数は増える。"""
    reset_data()
    ledger = ledger or Ledger()
    first = ["policy_collector", "expense_collector"]
    rest = ["analyst", "writer", "notifier"]
    workers = build_workers(first + rest, ledger)
    orch = Orchestrator(workers=workers, blackboard=Blackboard())

    with ThreadPoolExecutor(max_workers=len(first)) as pool:
        futures = [pool.submit(workers[role].run, ROLE_TASKS[role], f"TASK-008P-{i:02d}")
                   for i, role in enumerate(first, start=1)]
        trajectories = [f.result() for f in futures]  # submit した順に受け取る

    # 黒板への書き込み順は**自分で固定する**。並列のまま書くと軌跡が再現しない
    for role, traj in zip(first, trajectories):
        orch.trajectories[role] = traj
        orch.blackboard.write(role, "result", traj.final or "")
        workers[role].publish(orch.blackboard)

    for i, role in enumerate(rest, start=len(first) + 1):
        context = context_from_blackboard(orch.blackboard, NEEDS[role])
        if context:
            ledger.record_hop("親", role, context)
        orch.dispatch(role, format_handoff(ROLE_TASKS[role], context), f"TASK-008P-{i:02d}")
        workers[role].publish(orch.blackboard)

    layers = [first] + [[r] for r in rest]
    return finish("オーケストレータ（並列・構造化）", ledger, orch.trajectories, layers,
                  orch.blackboard)


# ---------------------------------------------------------------------------
# 3. ハンドオフ型（横に渡す）
# ---------------------------------------------------------------------------
ROUTE = {"collector": "analyst", "analyst": "writer", "writer": "notifier",
         "notifier": None}

HANDOFF_LABELS = {
    "own": "ハンドオフ（自分の成果だけ）",
    "carry": "ハンドオフ（畳んで渡す）",
    "needs": "ハンドオフ（相手の要求に合わせる）",
    "free": "ハンドオフ（自由文）",
}


def handoff_payload(role: str, next_role: str, worker: Worker, received: dict[str, str],
                    traj, mode: str) -> dict[str, str]:
    """送り手が梱包する。**ここが方式の違いの本体**。

    own   … 自分が作ったものだけを渡す（受け取ったものは転送しない）
    carry … 受け取ったものに自分の成果を足して渡す（落とさないが膨らむ）
    needs … 相手が必要とする鍵だけを渡す（契約を共有していないとできない）
    free  … 自分の最終回答（自由文）だけを渡す
    """
    if mode == "free":
        return {"previous_result": traj.final or ""}
    if mode == "own":
        return pack(PRODUCES.get(role, ()), worker.facts)
    if mode == "carry":
        return {**received, **pack(PRODUCES.get(role, ()), worker.facts)}
    if mode == "needs":
        return pack(NEEDS[next_role], worker.facts)
    raise ValueError(f"未知の mode です: {mode!r}（own / carry / needs / free）")


def run_handoff(mode: str = "carry", ledger: Ledger | None = None) -> dict:
    """親を置かず、隣へ渡していく。次の相手は動いているエージェントが決める。"""
    if mode not in HANDOFF_LABELS:
        raise ValueError(f"mode は {sorted(HANDOFF_LABELS)} のいずれかです: {mode!r}")
    reset_data()
    ledger = ledger or Ledger()
    order = ["collector", "analyst", "writer", "notifier"]
    workers = build_workers(order, ledger)

    trajectories: dict = {}
    role: str | None = "collector"
    received: dict[str, str] = {}
    step = 0
    while role is not None:
        step += 1
        worker = workers[role]
        traj = worker.run(format_handoff(ROLE_TASKS[role], received),
                          task_id=f"TASK-008H-{step:02d}")
        trajectories[role] = traj
        next_role = ROUTE[role]
        if next_role is None:
            break
        payload = handoff_payload(role, next_role, worker, received, traj, mode)
        ledger.record_hop(role, next_role, payload)
        # 渡す相手と渡す情報を1つの値にまとめる（agentkit の型をそのまま使う）
        handoff = Handoff(to=next_role, task=ROLE_TASKS[next_role], context=payload)
        role, received = handoff.to, handoff.context

    return finish(HANDOFF_LABELS[mode], ledger, trajectories, [[r] for r in order])


if __name__ == "__main__":
    for result in (run_solo(), run_orchestrator("structured"), run_handoff("own")):
        s = result["score"]
        print(f"{result['方式']}: 手数={result['ledger'].total_calls} "
              f"段数={result['stages']} 採点={s['passed']}/{s['total']} "
              f"欠け={s['missing']}")
