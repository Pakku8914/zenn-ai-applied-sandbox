"""問題3の解答：先に伏せてから切る preview()。切ってから伏せると、途中で切れたメールやキーが形を失い、伏せ損なう。"""

from __future__ import annotations

from .mask import mask_text


def preview_bad(text: str, limit: int) -> str:
    """Bad：切ってから伏せる。"""
    cut = text if len(text) <= limit else text[:limit] + "…"
    return mask_text(cut)


def preview(text: str, limit: int) -> str:
    """Good：伏せてから切る。切ったときだけ末尾に … を付ける。"""
    masked = mask_text(text)
    return masked if len(masked) <= limit else masked[:limit] + "…"
