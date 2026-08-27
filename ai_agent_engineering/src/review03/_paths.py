"""復習03のコードから、agentkit と S10〜S12 の実装を import できるようにする。

復習03は「安全性の設計レビュー」を横断で問う。そのため、承認（S10）・信頼性（S11）・
注入と権限（S12）の実装をそのまま持ってきて組み合わせる。

  ROOT              … sandbox/（agentkit がある場所）
  tools             … make_data.py（業務データを初期状態に戻す）
  src/session10     … policy.py / gate.py / audit.py
  src/session11     … failure_kinds.py / guards.py / idempotency.py / retry_runner.py
  src/session12     … boundary.py / defenses.py / layers.py / ex_content_guard.py

**S09（隔離）のディレクトリは経路に足していない。** `src/session09/policy.py` と
`src/session10/policy.py` は同じ名前なので、両方を経路に入れると `import policy` が
どちらを選ぶかが読みにくくなる。この章では隔離を「compose の指定」という**仕様データ**
としてレビューする（境界が実際に破れていないことの確認は S09 の `probes.py` の担当）。

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
    ROOT / "src" / "session10",
    ROOT / "src" / "session11",
    ROOT / "src" / "session12",
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

    副作用を出す測定の前後で必ず呼ぶ。戻さないと2回目の測定が1回目の残骸を数える。
    """
    setup()
    import make_data  # noqa: PLC0415

    with contextlib.redirect_stdout(io.StringIO()):
        make_data.main()
