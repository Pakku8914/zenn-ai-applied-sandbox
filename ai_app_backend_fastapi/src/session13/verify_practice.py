"""Session 13 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session13

verify.py の後に実行される前提ではない（自分で s13 を作り直す）。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kondate.clock import JST, FixedClock
from kondate.db import SessionLocal, engine
from kondate.verifykit import check, eq, finish
from src.session13.budget import BudgetState
from src.session13.harness import (CHAT, LIGHT, clear_events, clear_redis, dbcheck, prepare_db, redis_client, rows,
                                   usd)
from src.session13.limiter import Limiter
from src.session13.metering import UsageRecord, save_usage
from src.session13.plans import PlanLimits
from src.session13.pricing import cost_usd, load_price_table
from src.session13.providers import Usage
from src.session13.q1_lookup import find_event
from src.session13.q2_breakdown import cost_breakdown, display_usd
from src.session13.q3_by_user import usage_by_user
from src.session13.q4_breakeven import breakeven_calls, calls_cost
from src.session13.q5_reconcile import reconcile_quota
from src.session13.q6_budget_hold import BudgetHold
from src.session13.q7_pending import PENDING_KEY, flush_pending, save_or_park

TABLE = load_price_table()
FREE = PlanLimits(10, 20_000)
T0 = FixedClock().now()  # 2026-10-02 18:00 JST


def rec(request_id: str, user_id: str, at: datetime, usage: Usage, source: str = "upstream",
        outcome: str = "completed") -> UsageRecord:
    return UsageRecord(request_id, user_id, CHAT, at, usage, source, outcome)


async def _setup() -> None:
    try:
        await prepare_db()
    finally:
        await engine.dispose()


asyncio.run(_setup())


@dbcheck("P1 request_id で自分の記録だけを引く（他人の request_id は None）")
async def _():
    await clear_events()
    await save_usage(SessionLocal, rec("req_q1", "u001", T0, Usage(34, 20)), TABLE)
    async with SessionLocal() as s:
        mine = await find_event(s, "u001", "req_q1")
        other = await find_event(s, "u002", "req_q1")
        missing = await find_event(s, "u001", "req_none")
    eq((mine.outcome, mine.usage_source, mine.input_tokens, mine.output_tokens, usd(mine.cost_usd)),
       ("completed", "upstream", 34, 20, "0.00026800"), "自分の記録")
    eq((other, missing), (None, None), "他人・無い ID")
    return "u001 は自分の記録を引ける（completed・upstream・34／20・0.00026800）／u002 が同じ ID を引くと None・無い ID も None"


@check("P2 金額を4種に分けて出す（合計は cost_usd と一致）。表示の丸めは最後に1回だけ")
def _():
    usage = Usage(30, 181, 1084, 0)
    price = TABLE.price_for(CHAT, T0)
    chat = cost_breakdown(usage, price)
    light = cost_breakdown(usage, TABLE.price_for(LIGHT, T0))
    eq({k: usd(v) for k, v in chat.items()}, {"input": "0.00006000", "output": "0.00181000",
                                             "cache_write": "0.00000000", "cache_read": "0.00021680",
                                             "total": "0.00208680"}, "チャット用")
    eq((chat["total"], usd(light["total"])), (cost_usd(usage, price), "0.00104340"), "合計")
    eq((display_usd(chat["total"]), display_usd(light["total"])), ("$0.0021", "$0.0010"), "表示")
    return ("入力 0.00006000・出力 0.00181000・作成 0.00000000・読み出し 0.00021680・合計 0.00208680／"
            "軽い処理用は 0.00104340／表示は $0.0021・$0.0010")


@dbcheck("P3 1日の利用者別の集計（金額の多い順・JST の日付）")
async def _():
    await clear_events()
    for r in (rec("req_q3_1", "u001", datetime(2026, 10, 2, 0, 0, tzinfo=JST), Usage(34, 20)),
              rec("req_q3_2", "u001", T0, Usage(30, 181, 1084, 0)),
              rec("req_q3_3", "u002", datetime(2026, 10, 2, 12, 0, tzinfo=JST), Usage(34, 20)),
              rec("req_q3_4", "u003", datetime(2026, 10, 1, 23, 59, 59, tzinfo=JST), Usage(34, 20)),
              rec("req_q3_5", "u004", datetime(2026, 10, 3, 0, 0, tzinfo=JST), Usage(34, 20))):
        await save_usage(SessionLocal, r, TABLE)
    async with SessionLocal() as s:
        got = await usage_by_user(s, date(2026, 10, 2))
    eq([(u.user_id, u.requests, u.tokens, usd(u.cost_usd), u.unpriced) for u in got],
       [("u001", 2, 1349, "0.00235480", 0), ("u002", 1, 54, "0.00026800", 0)], "10月2日")
    return "u001 2件・1349・0.00235480 → u002 1件・54・0.00026800（10月1日 23:59:59 と10月3日 0:00 の行は入らない）"


@check("P4 キャッシュの損益分岐：接頭辞 1084 は2回目から得。接頭辞 364 はキャッシュされない")
def _():
    chat, light = TABLE.price_for(CHAT, T0), TABLE.price_for(LIGHT, T0)
    got = [(usd(calls_cost(1084, 30, 181, chat, n, cached=True)), usd(calls_cost(1084, 30, 181, chat, n,
                                                                                    cached=False)))
           for n in (1, 2, 5)]
    eq(got, [("0.00458000", "0.00403800"), ("0.00666680", "0.00807600"), ("0.01292720", "0.02019000")],
       "回数ごとの合計（キャッシュあり, なし）")
    eq((breakeven_calls(1084, chat), breakeven_calls(1084, light), breakeven_calls(364, chat)), (2, 2, None),
       "損益分岐")
    return ("1回：0.00458000 対 0.00403800／2回：0.00666680 対 0.00807600／5回：0.01292720 対 0.02019000／"
            "損益分岐はどちらのモデルも2回・接頭辞 364 は None")


@dbcheck("P5 台帳（正）から Redis の使用量を作り直す。作り直す前は上限を超える予約が通ってしまう")
async def _():
    await clear_redis()
    await clear_events()
    await save_usage(SessionLocal, rec("req_q5", "u005", T0, Usage(19_000, 0)), TABLE)
    async with redis_client() as redis:
        lim = Limiter(redis)
        leaked = await lim.reserve("u005", FREE, 1058, T0, 600)  # Redis は使用量 0 だと思っている
        await lim.settle(leaked.reservation, 0)
        async with SessionLocal() as s:
            first = await reconcile_quota(lim, s, "u005", T0)
            second = await reconcile_quota(lim, s, "u005", T0)
        state = await lim.quota_state("u005", FREE, T0)
        blocked = await lim.reserve("u005", FREE, 1058, T0, 600)
    eq(leaked.reservation is not None, True, "作り直す前の予約")
    eq((first, second), ((0, 19000), (19000, 19000)), "(Redis, 台帳)")
    eq((state.used, blocked.reservation), (19000, None), "作り直したあと")
    return "作り直す前は予約 1058 が通る／(0, 19000) → 2回目は (19000, 19000) で変更なし／そのあと予約 1058 は通らない"


@check("P6 予算の保留（Redis）：同時の2件は1件だけ通す。台帳だけの判定は2件とも通してしまう")
async def _():
    await clear_redis()
    state = BudgetState(Decimal("0.05"), Decimal("0.03"), Decimal("0.01030800"))
    naive = [not state.exceeded, not state.exceeded]  # 2件とも、まだ記録の無い台帳を見て判定した
    async with redis_client() as redis:
        bh = BudgetHold(redis)
        holds = await asyncio.gather(bh.hold("u001", state, T0), bh.hold("u001", state, T0))
        granted = [h for h in holds if h is not None]
        third = await bh.hold("u001", state, T0)
        await bh.release(granted[0])
        after_release = await bh.hold("u001", state, T0)
        expired = await bh.hold("u001", state, T0 + timedelta(seconds=601))
    eq(naive, [True, True], "台帳だけの判定")
    eq((len(granted), third), (1, None), "同時の2件と続く1件")
    eq((after_release is not None, expired is not None), (True, True), "解放後・期限切れ後")
    return ("台帳だけでは2件とも通る（合計 0.05061600 > 0.05）／保留つきは同時の2件のうち1件だけ・続く1件も断る／"
            "解放すると通る／600秒を過ぎた保留は数えない")


@dbcheck("P7 台帳に書けない間は Redis に退避し、あとで流し込む（同じ request_id は二重に入らない）")
async def _():
    await clear_redis()
    await clear_events()
    a = rec("req_q7_a", "u001", T0, Usage(34, 20))
    b = rec("req_q7_b", "u001", T0, Usage(34, 12), "estimated", "client_disconnected")
    broken_engine = create_async_engine("postgresql+asyncpg://kondate:kondate@127.0.0.1:1/kondate")
    broken = async_sessionmaker(broken_engine, expire_on_commit=False)
    try:
        async with redis_client() as redis:
            first = await save_or_park(SessionLocal, redis, a, TABLE)
            parked = [await save_or_park(broken, redis, r, TABLE) for r in (a, b)]  # a は再送（もう台帳にある）
            queued = await redis.llen(PENDING_KEY)
            flushed = await flush_pending(SessionLocal, redis, TABLE)
            left = await redis.llen(PENDING_KEY)
    finally:
        await broken_engine.dispose()
    got = [r[0] for r in await rows("SELECT request_id FROM s13.usage_events ORDER BY request_id")]
    eq((first, parked, queued), ("saved", ["parked", "parked"], 2), "退避")
    eq((flushed, left, got), ((1, 1), 0, ["req_q7_a", "req_q7_b"]), "流し込み")
    return "DB に届かない間は2件とも退避（2件）→ 流し込みで新規1件・重複1件・残り 0／台帳は req_q7_a と req_q7_b の2行"


finish("session13-practice")
