"""最終プロジェクトのコードから、agentkit と S13〜S15 の実装を import できるようにする。

方針は中間プロジェクト01・02と同じ「**新しい部品を作らない**」である。使うのは次のものだけ。

  ROOT           … agentkit（軌跡・ツール・オラクル・状態機械）
  src/session13  … evalspec.py（評価仕様）/ scoreboard.py（指標）
  src/session14  … spanlog.py（軌跡からスパンの木を作る）
  src/session15  … opsconfig.py（運用の設定）

既存のファイルは1行も変更しない。足すのは import 経路だけである。

**名前を `_paths.py` にしていないのは意図的である。** 中間プロジェクト01と02はどちらも
`_paths.py` を持っており、`python -m pytest src` のようにまとめて収集すると、先に読み込ま
れた方が `sys.modules["_paths"]` を占める。そうなると、この章のコードが呼ぶ `setup()` が
別プロジェクトのもの（＝ S13〜S15 を通さない import 経路）になり、原因の分かりにくい
`ModuleNotFoundError` が出る。**同名モジュールの衝突は、引き継いだ人が最初に踏む地雷**
なので、ここでは名前を分けて踏まないようにしてある。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

_DIRS = (
    ROOT,
    ROOT / "src" / "session13",   # evalspec / scoreboard
    ROOT / "src" / "session14",   # spanlog
    ROOT / "src" / "session15",   # opsconfig
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
