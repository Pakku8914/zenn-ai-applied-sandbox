"""復習章のコードから、agentkit と S02〜S04 の実装を import できるようにする。

復習章は「複数セッションの成果物を組み合わせて初めて解ける」問題を扱う。
そのため、これまでのセッションのディレクトリを import 経路に足しておく。

  ROOT              … sandbox/（agentkit がある場所）
  src/session02     … decision.py / failure_modes.py / agent_book_room.py
  src/session03     … my_agent.py（MyReActAgent・recommend_max_steps・choose_on_limit）
  src/session04     … badtools.py / goodtools.py / toolschema.py / measure.py

既存のファイルは1行も変更しない。足すのは経路だけである。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_DIRS = (
    ROOT,
    ROOT / "src" / "session02",
    ROOT / "src" / "session03",
    ROOT / "src" / "session04",
)


def setup() -> Path:
    """import 経路を整えて sandbox のルートを返す。何度呼んでも安全。"""
    for directory in _DIRS:
        text = str(directory)
        if text not in sys.path:
            sys.path.insert(0, text)
    return ROOT
