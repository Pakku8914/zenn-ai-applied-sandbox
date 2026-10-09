"""練習問題4の解答：プロンプトキャッシュが何回目から得になるかを、単価表から計算する。"""

from __future__ import annotations

from decimal import Decimal

from .pricing import Price, cost_usd
from .providers import Usage

CACHE_MIN_TOKENS = 1024  # mockllm の規則。本物の最小長はモデルによって違う（公式ドキュメントで確かめる）


def calls_cost(prefix_tokens: int, rest_tokens: int, output_tokens: int, price: Price, calls: int, *,
               cached: bool) -> Decimal:
    """同じ接頭辞の要求を TTL の中で calls 回送ったときの合計（USD）。"""
    if calls < 1:
        raise ValueError("calls は1以上です")
    if not cached or prefix_tokens < CACHE_MIN_TOKENS:  # 短すぎる接頭辞は、印を付けてもキャッシュされない
        return cost_usd(Usage(prefix_tokens + rest_tokens, output_tokens), price) * calls
    first = cost_usd(Usage(rest_tokens, output_tokens, 0, prefix_tokens), price)
    later = cost_usd(Usage(rest_tokens, output_tokens, prefix_tokens, 0), price)
    return first + later * (calls - 1)


def breakeven_calls(prefix_tokens: int, price: Price, *, max_calls: int = 10) -> int | None:
    """キャッシュした方が安くなる最小の回数。接頭辞が短い・max_calls 回までに得にならないなら None。"""
    if prefix_tokens < CACHE_MIN_TOKENS:
        return None
    for n in range(1, max_calls + 1):
        # 接頭辞より後ろ（入力の残り・出力）はどちらも同じ額なので、接頭辞の分だけ比べればよい
        if calls_cost(prefix_tokens, 0, 0, price, n, cached=True) < calls_cost(prefix_tokens, 0, 0, price, n,
                                                                                cached=False):
            return n
    return None
