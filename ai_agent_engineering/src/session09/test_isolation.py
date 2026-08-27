#!/usr/bin/env python3
"""問題7の参照解答：隔離実行つきエージェントの軌跡テスト（セッション9）。

    python -m pytest src/session09 -q

`tool-runner` が動いていない環境では SKIP_RUNNER=1 を付けると丸ごと飛ばせる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.biztools import build_registry  # noqa: E402
from agentkit.llm import ScriptedClient  # noqa: E402
from agentkit.loop import ReActAgent  # noqa: E402
from agentkit.models import ToolCall  # noqa: E402
from agentkit.sandbox import make_run_python_tool  # noqa: E402
from agentkit.tools import ToolRegistry  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_RUNNER") == "1",
    reason="隔離実行コンテナ（tool-runner）が必要なテストです",
)


def build_agent(scenario: str = "run_python_compute") -> ReActAgent:
    """業務ツールに run_python を1本足したエージェント。"""
    registry = build_registry()
    registry.register(make_run_python_tool())
    return ReActAgent(ScriptedClient(scenario), registry, max_steps=8)


def test_隔離実行を挟んだ軌跡が期待どおり() -> None:
    traj = build_agent().run("経費の合計を出してください", task_id="TASK-901")
    assert traj.stop_reason == "done"
    assert traj.tool_names == ["list_expenses", "run_python"]
    assert "285,400" in (traj.final or "")


def test_二回実行しても同じ軌跡になる() -> None:
    a = build_agent().run("経費の合計を出してください", task_id="TASK-902")
    b = build_agent().run("経費の合計を出してください", task_id="TASK-902")
    assert a.tool_names == b.tool_names
    assert a.final == b.final


def test_隔離実行で集計できる() -> None:
    registry = ToolRegistry([make_run_python_tool()])
    code = ("amounts = [3200, 68000, 12800, 145000, 4400, 52000]\n"
            "print(sum(amounts))\n")
    result = registry.call(ToolCall("c0", "run_python", {"code": code}))
    assert result.ok, result.error
    assert result.content.strip() == "285400"


def test_タイムアウトはツール結果の失敗になる() -> None:
    registry = ToolRegistry([make_run_python_tool(timeout=2.0)])
    result = registry.call(ToolCall("c1", "run_python",
                                   {"code": "import time\ntime.sleep(30)"}))
    assert not result.ok
    assert "タイムアウト" in (result.error or "")


def test_外に出ようとしたコードは失敗する() -> None:
    registry = ToolRegistry([make_run_python_tool()])
    code = ("import socket\n"
            "socket.setdefaulttimeout(3)\n"
            "socket.create_connection(('1.1.1.1', 53))\n")
    result = registry.call(ToolCall("c2", "run_python", {"code": code}))
    assert not result.ok
    assert "OSError" in (result.error or "")
