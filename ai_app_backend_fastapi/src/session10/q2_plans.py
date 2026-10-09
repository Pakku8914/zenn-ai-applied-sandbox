"""練習問題2の解答：team プランを設定に足し、クォータの「日」と retry-after を1つの関数で返す。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .plans import LimitSettings, PlanLimits, jst_day, seconds_until_reset


class TeamLimitSettings(LimitSettings):
    """free・pro に team を足した設定。環境変数の接頭辞（LIMIT_）は親から引き継ぐ。"""

    team_requests_per_minute: int = Field(default=120, gt=0)
    team_tokens_per_day: int = Field(default=1_000_000, gt=0)

    def for_plan(self, plan: str) -> PlanLimits:
        if plan == "team":
            return PlanLimits(self.team_requests_per_minute, self.team_tokens_per_day)
        return super().for_plan(plan)


def quota_window(now: datetime) -> tuple[str, int]:
    """(クォータの日 YYYYMMDD, 次の 00:00 JST までの秒) を返す。タイムゾーンの無い時刻は断る。"""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("タイムゾーンの無い時刻は受け付けません")
    return jst_day(now), seconds_until_reset(now)
