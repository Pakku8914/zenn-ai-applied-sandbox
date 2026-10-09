"""練習問題1の解答：四捨五入（ROUND_HALF_UP）して、JSON にそのまま入れられる数にする。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def half_up(value: float | int | str | Decimal, places: int) -> int | float:
    # float を Decimal(value) にすると 2.675 → 2.67499999… になる。str を経由して「書かれた値」にする
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)  # places=2 → Decimal("0.01")
    return int(q) if q == q.to_integral_value() else float(q)  # 6.0 は 6 にそろえる
