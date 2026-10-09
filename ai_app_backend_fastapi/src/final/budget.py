"""予算の事前判定（402 budget_exceeded）。session13/budget.py のコピー（依存性の組み立ては chat.py に移した）。

「今月の使用額（台帳）＋この1回の見積もり」が予算を超えるなら、上流を呼ぶ前に断る。
単価表に無いモデルは見積もれないので、上流を呼ばずに 500 internal_error（0 円で通さない）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from .aggregate import cost_between, month_range
from .errors import ApiError
from .keys import CurrentUser
from .pricing import PriceTable, cost_usd
from .providers import Usage

logger = logging.getLogger("kondate.final.budget")


class BudgetSettings(BaseSettings):
    """月額の予算（USD）。例：BUDGET_FREE_MONTHLY_USD=2.00、BUDGET_USERS='{"u003": "0.05"}'（金額は文字列で）。"""

    model_config = SettingsConfigDict(env_prefix="BUDGET_", extra="ignore")

    free_monthly_usd: Decimal = Field(default=Decimal("1.00"), ge=0)
    pro_monthly_usd: Decimal = Field(default=Decimal("20.00"), ge=0)
    users: dict[str, Decimal] = Field(default_factory=dict)

    def monthly_for(self, user_id: str, plan: str) -> Decimal:
        if user_id in self.users:
            return self.users[user_id]
        return self.free_monthly_usd if plan == "free" else self.pro_monthly_usd


async def check_budget(session: AsyncSession, user: CurrentUser, *, model: str, input_estimate: int,
                       max_tokens: int, now: datetime, settings: BudgetSettings, table: PriceTable) -> Decimal:
    """見積もり（入力の見積もり＋max_tokens ぶんの出力）を返す。超えるなら 402、単価が無ければ 500。"""
    price = table.price_for(model, now)
    if price is None:
        logger.error("budget_unpriced_model", extra={"model": model, "user_id": user.id})
        raise ApiError(500, "internal_error")
    estimate = cost_usd(Usage(input_estimate, max_tokens), price)
    spent = await cost_between(session, user.id, *month_range(now))
    limit = settings.monthly_for(user.id, user.plan)
    if spent.priced_usd + estimate > limit:
        logger.info("budget_exceeded", extra={"user_id": user.id, "limit_usd": str(limit),
                                              "spent_usd": str(spent.priced_usd), "estimate_usd": str(estimate)})
        raise ApiError(402, "budget_exceeded")
    return estimate
