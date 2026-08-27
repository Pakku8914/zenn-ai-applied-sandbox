"""複数体構成の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/session08 -q

`ScriptedClient` と `FixedClock` を使うので、何度実行しても同じ結果になる。
「複数体にしたら賢くなった気がする」ではなく、**採点と副作用の回数**で判定する。
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

from conflict import race  # noqa: E402
from debug import first_loss  # noqa: E402
from privilege import SOLO_ALLOW, SPLIT_ALLOW, run_injected  # noqa: E402
from runners import run_handoff, run_orchestrator, run_solo  # noqa: E402
from sideeffects import reset_data  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    """毎回、業務データと成果物を初期状態に戻す。"""
    reset_data()
    yield
    reset_data()


def test_分けても成果物は変わらず手数だけ増える():
    solo, orchestrated = run_solo(), run_orchestrator("structured")
    assert solo["report"] == orchestrated["report"]
    assert solo["notices"][0]["body"] == orchestrated["notices"][0]["body"]
    assert (solo["ledger"].total_calls, orchestrated["ledger"].total_calls) == (5, 8)


def test_自由文で渡すと成果物が黙って劣化する():
    result = run_orchestrator("free")
    assert result["score"]["passed"] == 1
    # 失敗しているのに、どのワーカーも done で終わっている
    assert all(t.stop_reason == "done" for t in result["trajectories"].values())
    assert first_loss(result) == "親→analyst"


def test_自分の成果だけ渡すと通知の件数が落ちる():
    own = run_handoff("own")
    assert own["score"]["missing"] == ["通知に違反件数が入っている"]
    assert first_loss(own) == "writer→notifier"
    # 相手の要求に合わせて渡せば、同じ体数・同じ手数で 4/4 になる
    needs = run_handoff("needs")
    assert needs["score"]["passed"] == 4
    assert needs["ledger"].total_calls == own["ledger"].total_calls


def test_権限を分けると注入された送信が実行できない():
    solo = run_injected(SOLO_ALLOW, "単体", role="solo")
    split = run_injected(SPLIT_ALLOW, "分割")
    assert solo["送信件数"] == 1 and solo["宛先"] == ["external@example.com"]
    assert split["送信件数"] == 0
    assert split["拒否された操作"] == ["get_employee", "send_message"]


def test_書くのを1体に絞ると二重予約が消える():
    assert race("each")["予約行数"] == 2          # それぞれが書くと2件入る
    assert race("read_all")["予約行数"] == 1      # 決めるのは2体・書くのは1体
    assert race("latest_only")["予約行数"] == 0   # 最後の書き手の候補が競合枠だった
