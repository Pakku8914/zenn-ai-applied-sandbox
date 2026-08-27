"""復習04のコードから、agentkit と S13〜S15 の実装を import できるようにする。

復習04は「運用の意思決定」を横断で問う。測る（S13）・追う（S14）・回す（S15）の
実装をそのまま持ってきて、その出力を材料に「次の一手」を決める。

  ROOT           … sandbox/（agentkit がある場所）
  tools          … make_data.py（業務データを初期状態に戻す）
  src/session13  … evalspec.py / judges.py（評価仕様と判定方式3種＋厳格版）
  src/session14  … spanlog.py / breakdown.py / failtags.py（内訳と症状の集計）
  src/session15  … jobspec.py / queue_sim.py / ratelimit.py / swap.py /
                   rollout.py / opsconfig.py（キュー・差し替え・段階リリース）

**S16 のディレクトリは経路に足していない。** 支払う側の材料は、本章で宣言する
「仮の単価表」と月次のワークロードから自分で組み立てる（`budget.py`）。運用の判断は
単価表そのものが前提であり、前提を宣言せずに借りてくると議論が噛み合わなくなるためである。

既存のファイルは1行も変更しない。足すのは経路だけである。
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_DIRS = (
    ROOT,
    ROOT / "tools",
    ROOT / "src" / "session13",
    ROOT / "src" / "session14",
    ROOT / "src" / "session15",
)


def setup() -> Path:
    """import 経路を整えて sandbox のルートを返す。何度呼んでも安全。"""
    for directory in _DIRS:
        text = str(directory)
        if text not in sys.path:
            sys.path.insert(0, text)
    return ROOT


def reset_data() -> None:
    """業務データを初期状態に戻す（経費6件・予約0件・送信0件）。

    段階リリースと差し替えの測定は実際に社外宛の送信を出す。測定の前後で必ず呼ぶ。
    """
    setup()
    import make_data  # noqa: PLC0415

    with contextlib.redirect_stdout(io.StringIO()):
        make_data.main()
