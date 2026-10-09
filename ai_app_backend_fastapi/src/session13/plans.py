"""プラン別の上限（設定）と、クォータの「1日」の区切り（JST）。session10/plans.py のコピー。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kondate.clock import JST


@dataclass(frozen=True)
class PlanLimits:
    requests_per_minute: int
    tokens_per_day: int


class LimitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIMIT_", extra="ignore")

    free_requests_per_minute: int = Field(default=10, gt=0)
    free_tokens_per_day: int = Field(default=20_000, gt=0)
    pro_requests_per_minute: int = Field(default=60, gt=0)
    pro_tokens_per_day: int = Field(default=200_000, gt=0)
    hold_seconds: int = Field(default=600, gt=0)

    def for_plan(self, plan: str) -> PlanLimits:
        if plan == "free":
            return PlanLimits(self.free_requests_per_minute, self.free_tokens_per_day)
        if plan == "pro":
            return PlanLimits(self.pro_requests_per_minute, self.pro_tokens_per_day)
        raise ValueError(f"未知のプランです: {plan}")


def jst_day(now: datetime) -> str:
    return now.astimezone(JST).strftime("%Y%m%d")


def next_reset(now: datetime) -> datetime:
    today = now.astimezone(JST).date()
    return datetime.combine(today + timedelta(days=1), time(0), tzinfo=JST)


def seconds_until_reset(now: datetime) -> int:
    return max(1, math.ceil((next_reset(now) - now).total_seconds()))
