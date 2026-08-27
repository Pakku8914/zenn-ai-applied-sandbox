"""メモリの軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/session07 -q

`ScriptedClient` と `FixedClock` を使うので、何度実行しても同じ結果になる。
「収まったか」だけでなく「制約が残ったか」「指摘が出たか」まで機械判定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from agentkit.memory import ShortTermMemory, extract_constraints  # noqa: E402
from compress import apply_policy  # noqa: E402
from ex_memory import missing_rules, run_with_keep_summary  # noqa: E402
from longterm import AuditMemory, recall_modes, reset_data  # noqa: E402
from records import (breakdown, constraints, record, retention,  # noqa: E402
                     tokens)
from runner import MAX_CONTEXT, build, judge  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    """業務データを初期状態に戻す（予約が積み上がらないようにする）。"""
    reset_data()
    yield
    reset_data()


def run(policy: str):
    memory = AuditMemory(f"test_{policy}")
    memory.clear()
    runner = build(policy, longterm=memory)
    return runner, runner.run()


def test_記録は固定幅で近似トークンは記録数に比例する():
    rec = record("制約", "5万円以上は必ず事前承認が必要。")
    assert len(rec) == 33
    assert tokens([rec] * 180) == MAX_CONTEXT == 1_980


def test_既定のShortTermMemoryは何も圧縮しない():
    mem = ShortTermMemory(items=[record("ログ", f"07-{i:03d} 定例")
                                 for i in range(1, 241)], max_tokens=MAX_CONTEXT)
    assert mem.overflowing() and len(mem.items) == 240


def test_圧縮しないと溢れて打ち切られる():
    runner, traj = run("none")
    assert traj.stop_reason == "budget"
    assert len(traj.steps) == 4
    assert len(runner.memory.items) == 253
    assert runner.memory.total_tokens() == 2_783


def test_溢れる原因はツール結果が支配的():
    runner, _ = run("none")
    rows = {r["要素"]: r for r in breakdown(runner.memory.items)}
    assert rows["ツール結果"]["割合"] == 94.5
    assert rows["指示・制約"]["記録数"] == 10


@pytest.mark.parametrize(("policy", "records_", "constraints_", "findings"), [
    ("truncate", 181, 1, 0),
    ("summarize", 145, 6, 2),
    ("keep", 181, 7, 3),
    ("externalize", 27, 7, 3),
    ("summarize_all", 18, 0, 0),
])
def test_方式ごとの収まり方と成果(policy, records_, constraints_, findings):
    runner, traj = run(policy)
    assert traj.stop_reason == "done"
    assert len(runner.memory.items) == records_
    assert len(constraints(runner.memory.items)) == constraints_
    assert len(judge(runner.memory.items)) == findings


def test_同じ大きさでも残すものが違えば結果が変わる():
    trunc, _ = run("truncate")
    keep, _ = run("keep")
    assert trunc.memory.total_tokens() == keep.memory.total_tokens() == 1_991
    assert missing_rules(trunc.memory.items) == ["amount", "deadline", "note"]
    assert missing_rules(keep.memory.items) == []


def test_切り捨ては最初の制約から落とす():
    runner, _ = run("none")
    after = apply_policy("truncate", runner.memory)
    info = retention(runner.memory.items, after.items)
    assert info["残った制約"] == 1
    assert "5万円以上は必ず事前承認が必要。" in info["落ちた制約"]


def test_制約は正規表現だけでは拾いきれない():
    runner, _ = run("keep")
    tagged = []
    for rec in constraints(runner.first_seen):
        if rec not in tagged:
            tagged.append(rec)
    assert len(tagged) == 7
    assert len([r for r in tagged if extract_constraints(r)]) == 5


def test_制約を残す要約器なら指摘が3件に戻る():
    runner, traj = run_with_keep_summary()
    assert len(runner.memory.items) == 146
    assert len(judge(runner.memory.items)) == 3


def test_外部化した記録は行単位で引き戻せる():
    run("externalize")
    memory = AuditMemory("test_externalize")
    lines = memory.recall_lines("EXP-0004")
    assert len(lines) == 1 and "EXP-0004" in lines[0]


def test_期限切れの記憶は引かれない():
    memory = AuditMemory("test_forget")
    memory.clear()
    memory.remember("notice:工事", "みなと は7月末まで工事中", kind="notice",
                    expires_on="2026-07-31", source="設備部")
    assert all("工事" not in hit["body"] for hit in memory.recall("みなと 工事"))
    assert memory.forget_expired() == 1


def test_引かないと1回失敗し直前だけ引けば失敗しない():
    rows = {r["方式"]: r for r in recall_modes()}
    assert (rows["none"]["失敗"], rows["none"]["引いた回数"]) == (1, 0)
    assert (rows["conditional"]["失敗"], rows["conditional"]["引いた回数"]) == (0, 1)
    assert rows["always"]["引いた回数"] == 3
