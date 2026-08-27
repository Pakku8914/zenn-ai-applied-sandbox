"""中間プロジェクト02のコードから、agentkit と既習セッションの実装を import できるようにする。

方針は中間プロジェクト01と同じ「**新しい部品を作らない**」である。使うのは次のものだけ。

  ROOT           … agentkit（軌跡・ツール・オラクル・状態機械・時計・隔離実行・承認ゲート）
  src/session04  … goodtools.py（改善版ツール・冪等キー付き申請）/ toolschema.py（スキーマ検証）
  src/session10  … policy.py（可逆性×影響範囲の判定）/ gate.py（承認ゲート）/ audit.py（監査ログ）
  src/session11  … failure_kinds.py / guards.py / faults.py / backoff.py / idempotency.py /
                   compensate.py（再試行の判断・上限・障害注入・補償）
  src/session12  … boundary.py / defenses.py / ex_content_guard.py（信頼境界・出力検査）
  src/session09  … guard.py（隔離実行の唯一の入口）

既存のファイルは1行も変更しない。足すのは import 経路だけである。

**並び順に意味がある。** `policy.py` は S09 と S10 の両方にあるので、S10 を先に置いて
S10 の判定表（可逆性×影響範囲）が選ばれるようにし、S09 は最後に置く。S09 側でこの章が
使うのは `guard.py` だけで、この名前は S09 にしか無いため、順序を下げても届く。
同名モジュールがある環境では、**import 経路の順序そのものが仕様**である。

自分のディレクトリを先頭に置くのも同じ理由である（`verify.py` のように他のセッションにも
同じ名前のファイルがあるため、先頭に置いておけば常に自分のものが選ばれる）。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

_DIRS = (
    ROOT,
    ROOT / "src" / "session04",
    ROOT / "src" / "session10",   # policy.py はこちらを使う（S09 より先に置く）
    ROOT / "src" / "session11",
    ROOT / "src" / "session12",
    ROOT / "src" / "session09",   # guard.py だけを使う（policy.py は使わない）
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
