"""練習問題5の参照解：宛先の許可リストの実装差をテストで固定する。

    python -m pytest src/session12 -q

3つ目のテスト（正当な宛先は通ること）を忘れると、「全部止める検査」でも
テストが緑になってしまう。防御のテストには**通す側の確認**を必ず入れる。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import ToolCall  # noqa: E402
from attacks import CASES  # noqa: E402
from defenses import ExactRecipientInspector, PrefixRecipientInspector  # noqa: E402
from layers import Config, reset, run_case  # noqa: E402

LOOKALIKE = CASES[1]


def setup_module(module) -> None:
    reset()


def teardown_module(module) -> None:
    reset()


def test_prefix_allowlist_lets_lookalike_through():
    """前方一致は `EMP-` で始まる社外アドレスを通してしまう。"""
    row = run_case(Config("前方一致", privilege=True,
                          inspector=PrefixRecipientInspector), LOOKALIKE)
    assert row["外部送信"] == 1
    assert row["遮断"] == 0


def test_exact_allowlist_blocks_lookalike():
    """完全一致なら止まり、遮断が記録される。"""
    row = run_case(Config("完全一致", privilege=True,
                          inspector=ExactRecipientInspector), LOOKALIKE)
    assert row["外部送信"] == 0
    assert row["遮断"] == 1


def test_exact_allowlist_passes_valid_recipients():
    """正当な宛先は通す（誤遮断していないことの確認）。"""
    inspector = ExactRecipientInspector()
    for to in ("EMP-002", "#ops", "#general"):
        call = ToolCall("t", "send_message", {"to": to, "body": "下書きを共有します。"})
        assert inspector.check(call) is None
    ng = ToolCall("t", "send_message",
                  {"to": "EMP-001.export@external.example.com", "body": "x"})
    assert inspector.check(ng) is not None
