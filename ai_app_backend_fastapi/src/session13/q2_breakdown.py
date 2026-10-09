"""練習問題2の解答：金額を4種のトークンに分けて出し、表示用の丸めは最後に1回だけ行う。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .pricing import MILLION, USD_PLACES, Price
from .providers import Usage


def cost_breakdown(usage: Usage, price: Price) -> dict[str, Decimal]:
    """{"input", "output", "cache_write", "cache_read", "total"}（USD・小数8桁）。total は cost_usd と同じ値。"""
    pairs = {
        "input": (usage.input_tokens, price.input),
        "output": (usage.output_tokens, price.output),
        "cache_write": (usage.cache_creation_input_tokens, price.cache_write),
        "cache_read": (usage.cache_read_input_tokens, price.cache_read),
    }
    parts = {name: (tokens * unit / MILLION).quantize(USD_PLACES) for name, (tokens, unit) in pairs.items()}
    parts["total"] = sum(parts.values(), Decimal(0))
    return parts


def display_usd(amount: Decimal) -> str:
    """画面に出すときだけ小数4桁に四捨五入する（台帳や合計の計算には使わない）。"""
    return "$" + format(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
