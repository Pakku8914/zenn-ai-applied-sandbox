"""前半・練習問題3の解答のテスト：録画済みの2本のカセットを要約する（mockllm も DB も使わない）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..testkit import PROMPT
from .cassette_summary import summarize_cassette

CASSETTES = Path(__file__).resolve().parents[1] / "tests" / "cassettes"


@pytest.mark.parametrize(("name", "shape", "chars", "usage"), [
    ("chat_ok", "TextDelta×32 → Done", 192, (34, 181)),
    ("chat_sse_error", "TextDelta×2 → ProviderError(stream_error)", 12, None),
])
def test_summarize(name: str, shape: str, chars: int, usage: tuple[int, int] | None) -> None:
    [summary] = summarize_cassette(CASSETTES / f"{name}.jsonl")  # どちらも上流への呼び出しは1回
    assert (summary["call"], summary["prompt"]) == ("stream", PROMPT)
    assert (summary["shape"], summary["chars"], summary["usage"]) == (shape, chars, usage)
