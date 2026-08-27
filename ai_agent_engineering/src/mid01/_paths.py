"""中間プロジェクト01のコードから、agentkit と既習セッションの実装を import できるようにする。

このプロジェクトの方針は「新しい部品を作らない」である。使うのは次のものだけ。

  ROOT              … agentkit（軌跡・ツール・オラクル・状態機械・時計）
  src/session02     … failure_modes.py（失敗モード5分類・識別子の正規表現 ID_PATTERN）
  src/session04     … goodtools.py / toolschema.py（改善版ツールとスキーマ検証）
  src/session05     … planner.py（Plan / SubGoal / validate_plan / mermaid_dag）
  src/review01      … diagnose.py（原因6分類・done の裏取り）

既存のファイルは1行も変更しない。足すのは import 経路だけである。

自分のディレクトリを**先頭**に置くのが要点。`verify.py` のように他のセッションにも
同じ名前のファイルがあるため、先頭に置いておけば常に自分のものが選ばれる。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

_DIRS = (
    ROOT,
    ROOT / "src" / "session02",
    ROOT / "src" / "session04",
    ROOT / "src" / "session05",
    ROOT / "src" / "review01",
)


def setup() -> Path:
    """import 経路を整えて sandbox のルートを返す。何度呼んでも安全。"""
    here = str(HERE)
    if here in sys.path:
        sys.path.remove(here)
    sys.path.insert(0, here)
    for directory in _DIRS:
        text = str(directory)
        if text not in sys.path:
            sys.path.append(text)
    return ROOT
