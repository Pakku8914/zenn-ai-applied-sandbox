"""単価表（日付つきのデータ）と金額の計算（session13/pricing.py のコピー。prices.json も同じ内容をコピーした）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from kondate.clock import JST

from .providers import Usage

PRICES_PATH = Path(__file__).with_name("prices.json")
MILLION = Decimal(1_000_000)
USD_PLACES = Decimal("0.00000001")
PRICE_FIELDS = ("input", "output", "cache_write", "cache_read")


@dataclass(frozen=True)
class Price:
    model: str
    effective_from: date
    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


def validate_rows(rows: tuple[Price, ...]) -> tuple[Price, ...]:
    seen: set[tuple[str, date]] = set()
    for p in rows:
        key = (p.model, p.effective_from)
        if key in seen:
            raise ValueError(f"同じモデル・同じ適用開始日の単価が2つあります: {p.model} {p.effective_from}")
        seen.add(key)
        for name in PRICE_FIELDS:
            value = getattr(p, name)
            if not isinstance(value, Decimal) or value < 0 or value.as_tuple().exponent < -2:
                raise ValueError(f"{p.model} の {name}: 単価は 0 以上・小数2桁までの Decimal です（{value!r}）")
    return rows


@dataclass(frozen=True)
class PriceTable:
    source: str
    checked_on: date
    rows: tuple[Price, ...]

    def price_for(self, model: str, at: datetime) -> Price | None:
        """at（記録の時刻）に効いていた単価。表に無いモデル・最初の適用開始日より前なら None。"""
        day = at.astimezone(JST).date()
        candidates = [p for p in self.rows if p.model == model and p.effective_from <= day]
        return max(candidates, key=lambda p: p.effective_from, default=None)


def _decimal(raw: object, where: str) -> Decimal:
    if not isinstance(raw, str):
        raise ValueError(f"{where}: 単価は文字列で書いてください（{raw!r}）")
    return Decimal(raw)


def parse_price_table(data: dict) -> PriceTable:
    rows = tuple(
        Price(model=r["model"], effective_from=date.fromisoformat(r["effective_from"]),
              **{name: _decimal(r[name], f"{r['model']} の {name}") for name in PRICE_FIELDS})
        for r in data["prices"])
    return PriceTable(data["source"], date.fromisoformat(data["checked_on"]), validate_rows(rows))


@lru_cache
def load_price_table(path: Path = PRICES_PATH) -> PriceTable:
    return parse_price_table(json.loads(path.read_text(encoding="utf-8")))


def get_price_table() -> PriceTable:
    return load_price_table()


PriceTableDep = Annotated[PriceTable, Depends(get_price_table)]


def cost_usd(usage: Usage, price: Price) -> Decimal:
    micro = (usage.input_tokens * price.input
             + usage.output_tokens * price.output
             + usage.cache_creation_input_tokens * price.cache_write
             + usage.cache_read_input_tokens * price.cache_read)
    return (micro / MILLION).quantize(USD_PLACES)
