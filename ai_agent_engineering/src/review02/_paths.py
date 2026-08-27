"""復習02のコードから、agentkit と S05・S06 の実装を import できるようにする。

復習02は「状態・メモリ・複数体という構造の選択」を横断で問う。そのため、
計画（S05）と状態機械（S06）の実装をそのまま持ってきて組み合わせる。

  ROOT              … sandbox/（agentkit がある場所）
  src/session05     … planner.py（SubGoal / validate_plan / topo_layers / plan_cost）
  src/session06     … states.py / runner.py / scenarios.py / durability.py

**挿入する順序に意味がある。** `sys.path.insert(0, ...)` を上から順に呼ぶので、
最後に入れた `src/session06` が先頭に来る。S05 と S06 にはどちらも `runner.py`
があるため、`import runner` で S06 の `ResumableRunner` が選ばれるようにしている。

既存のファイルは1行も変更しない。足すのは経路だけである。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_DIRS = (
    ROOT,
    ROOT / "src" / "session05",
    ROOT / "src" / "session06",  # 最後＝sys.path の先頭。runner は S06 のものを使う
)


def setup() -> Path:
    """import 経路を整えて sandbox のルートを返す。何度呼んでも安全。"""
    for directory in _DIRS:
        text = str(directory)
        if text not in sys.path:
            sys.path.insert(0, text)
    return ROOT
