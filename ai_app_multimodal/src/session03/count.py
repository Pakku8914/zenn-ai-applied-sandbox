"""count_tokens で入力トークンを確かめる（課金なし・決定的）。"""

from __future__ import annotations

from anthropic import Anthropic

from kondate.settings import get_settings

FRAME_TOKENS = 4 + 3  # mockllm の式で、リクエスト1件（4）とメッセージ1件（3）の枠の分


def count_input_tokens(client: Anthropic, content: list[dict]) -> int:
    """content を user メッセージ1件として送ったときの input_tokens を返す。"""
    res = client.messages.count_tokens(
        model=get_settings().llm_model,
        messages=[{"role": "user", "content": content}],
    )
    return res.input_tokens
