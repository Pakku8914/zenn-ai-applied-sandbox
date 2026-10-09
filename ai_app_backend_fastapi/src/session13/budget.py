"""予算の事前判定（402 budget_exceeded）。final はこのファイルをコピーし、BudgetDep をルートに足す。

予算はユーザー別の月額 USD を設定で持つ（BUDGET_USERS で1人ずつ、無ければプランの既定値）。
「今月の使用額（台帳）＋この1回の見積もり」が予算を超えるなら、上流を呼ぶ前に断る。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from .aggregate import cost_between, month_range
from .auth import ClockDep
from .deps import SessionDep
from .errors import ApiError
from .inputs import ChatDep
from .keys import CurrentUser
from .pricing import Price, PriceTable, PriceTableDep, cost_usd
from .providers import ChatRequest, Usage
from .ratelimit import RateLimitDep
from .relay import estimate_input_tokens

logger = logging.getLogger("kondate.session13.budget")


class BudgetSettings(BaseSettings):
    """月額の予算（USD）。例：BUDGET_FREE_MONTHLY_USD=2.00、BUDGET_USERS='{"u003": "0.05"}'（金額は文字列で）。"""

    model_config = SettingsConfigDict(env_prefix="BUDGET_", extra="ignore")

    free_monthly_usd: Decimal = Field(default=Decimal("1.00"), ge=0)
    pro_monthly_usd: Decimal = Field(default=Decimal("20.00"), ge=0)
    users: dict[str, Decimal] = Field(default_factory=dict)  # ユーザー別の上書き

    def monthly_for(self, user_id: str, plan: str) -> Decimal:
        if user_id in self.users:
            return self.users[user_id]
        if plan == "free":
            return self.free_monthly_usd
        if plan == "pro":
            return self.pro_monthly_usd
        raise ValueError(f"未知のプランです: {plan}")


def get_budget_settings() -> BudgetSettings:
    return BudgetSettings()


BudgetSettingsDep = Annotated[BudgetSettings, Depends(get_budget_settings)]


@dataclass(frozen=True)
class BudgetState:
    limit_usd: Decimal  # 今月の予算
    spent_usd: Decimal  # 台帳にある今月の使用額
    estimate_usd: Decimal  # この1回が使いうる額の見積もり

    @property
    def exceeded(self) -> bool:
        return self.spent_usd + self.estimate_usd > self.limit_usd


class UnpricedModelError(Exception):
    """いま送ろうとしているモデルの単価が単価表に無い（金額を見積もれない）。"""


def estimate_cost(chat: ChatRequest, price: Price) -> Decimal:
    """この1回の見積もり＝入力の見積もり＋max_tokens ぶんの出力（キャッシュは考えない）。"""
    return cost_usd(Usage(estimate_input_tokens(chat), chat.max_tokens), price)


async def budget_state(session: AsyncSession, user: CurrentUser, chat: ChatRequest, now: datetime,
                       settings: BudgetSettings, table: PriceTable) -> BudgetState:
    price = table.price_for(chat.model or "", now)
    if price is None:  # 見積もりを 0 にして通すと、予算の判定が黙って効かなくなる
        raise UnpricedModelError(chat.model)
    spent = await cost_between(session, user.id, *month_range(now))
    if spent.unpriced:
        logger.warning("budget_spent_has_unpriced user_id=%s unpriced=%d", user.id, spent.unpriced)
    return BudgetState(settings.monthly_for(user.id, user.plan), spent.priced_usd, estimate_cost(chat, price))


async def enforce_budget(chat: ChatDep, admission: RateLimitDep, session: SessionDep, settings: BudgetSettingsDep,
                         table: PriceTableDep, clock: ClockDep) -> BudgetState:
    """予算判定の依存性。レート制限を通ったあと（DB を読むので、回数の制限より後に置く）・予約の前に効く。

    単価表に無いモデルは、上流を呼ばずに 500 internal_error にする（金額を数えられない呼び出しをしない）。
    """
    try:
        state = await budget_state(session, admission.user, chat, clock.now(), settings, table)
    except UnpricedModelError:
        logger.error("budget_unpriced_model model=%s user_id=%s", chat.model, admission.user.id)
        raise ApiError(500, "internal_error") from None
    if state.exceeded:
        logger.info("budget_exceeded user_id=%s limit_usd=%s spent_usd=%s estimate_usd=%s",
                    admission.user.id, state.limit_usd, state.spent_usd, state.estimate_usd)
        raise ApiError(402, "budget_exceeded")
    return state


BudgetDep = Annotated[BudgetState, Depends(enforce_budget)]
