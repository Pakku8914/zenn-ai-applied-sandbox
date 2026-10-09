"""Session 8 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session08
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from kondate.verifykit import check, eq, finish
from src.session08 import tools as T
from src.session08.app import app, get_provider, get_tool_context
from src.session08.harness import brief, call, fixed_context, post_events
from src.session08.loop import STEP_LIMIT, LoopDone, ToolLimits, ToolResult, execute_tool, run_tool_loop
from src.session08.providers import (ChatRequest, FakeProvider, ToolCall, ToolCallDelta, ToolCallStart, Usage,
                                     fake_script)
from src.session08.q1_round import half_up
from src.session08.q2_shopping import make_shopping_list
from src.session08.q3_classify import INPUTS, PREDICTIONS
from src.session08.q4_assemble import BrokenToolCall, assemble_tool_calls
from src.session08.q5_rebuild import rebuild_messages
from src.session08.q6_dedup import DUPLICATE, dedup_tools
from src.session08.q7_parallel import TOO_MANY, execute_all


@check("P1 四捨五入：Decimal(str(x)) と ROUND_HALF_UP で、round() と違う値になる例")
def _():
    eq([half_up(1.25, 1), half_up(0.125, 2), half_up(2.675, 2), half_up(2.5, 0)], [1.3, 0.13, 2.68, 3], "half_up")
    eq([round(1.25, 1), round(0.125, 2), round(2.675, 2), round(2.5)], [1.2, 0.12, 2.67, 2], "round()")
    eq(Decimal(2.675).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), Decimal("2.67"), "Decimal(float) のまま")
    eq((half_up(6.0, 1), type(half_up(6.0, 1)).__name__), (6, "int"), "整数になったら int")
    return "half_up → 1.3・0.13・2.68・3／round() → 1.2・0.12・2.67・2／Decimal(2.675) のままだと 2.67"


@check("P2 make_shopping_list を本章3節のツールの規則どおりに実装する")
def _():
    ctx = fixed_context()
    cases = [dict(recipe_ids=["R001"]), dict(recipe_ids=["R001"], servings=1, have=["塩"]),
             dict(recipe_ids=["R001", "R067"], servings=4, have=["塩", "こしょう"]), dict(recipe_ids=["R001", "R001"])]
    for c in cases:
        args = T.MakeShoppingListIn(**c)
        eq(make_shopping_list(args, ctx), T.make_shopping_list(args, ctx), f"{c}")
    four = {i["name"]: (i["amount"], i["unit"]) for i in
            make_shopping_list(T.MakeShoppingListIn(**cases[2]), ctx)["items"]}
    eq((len(four), four["キャベツ"], four["にんじん"]), (9, (900, "g"), (0.6, "本")), "R001 + R067 を4人分")
    try:
        make_shopping_list(T.MakeShoppingListIn(recipe_ids=["R001", "R998", "R999"]), ctx)
        raise AssertionError("ToolError が出ない")
    except T.ToolError as e:
        eq(str(e), "レシピ R998, R999 はありません。search_recipes の結果にある id を指定してください。", "存在しない ID")
    return "4 通りで tools.py と一致・R001 + R067 を4人分 → 9 品（キャベツ 900 g・にんじん 0.6 本）・存在しない ID はまとめて ToolError"


@check("P3 入力がどこで止まるか（検証／ツールの中／成功）の予想が実際と一致する")
async def _():
    ctx = fixed_context()
    actual = {}
    for key, (name, input_) in INPUTS.items():
        r = await execute_tool(call(name, input_), ctx)
        actual[key] = "ok" if not r.is_error else ("schema" if r.output.startswith("引数が正しくありません") else "tool")
    eq(actual, PREDICTIONS, "予想")
    return "a=ok・b=schema・c=tool・d=tool・e=schema・f=ok・g=schema・h=schema"


@check("P4 ToolCallStart と ToolCallDelta だけから組み立て直す（交互に届く・壊れた JSON）")
def _():
    a = ToolCall("t1", "search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20})
    b = ToolCall("t2", "get_recipe", {"recipe_id": "R001"})
    seq = [e for e in fake_script("探します。", tool_calls=[a, b]) if isinstance(e, (ToolCallStart, ToolCallDelta))]
    eq(assemble_tool_calls(fake_script("探します。", tool_calls=[a, b])), [a, b], "順に届く場合")
    starts = [e for e in seq if isinstance(e, ToolCallStart)]
    da = [e for e in seq if isinstance(e, ToolCallDelta) and e.id == "t1"]
    db = [e for e in seq if isinstance(e, ToolCallDelta) and e.id == "t2"]
    mixed = [*starts, *[x for pair in zip(da, db + [None] * len(da)) for x in pair if x is not None]]
    eq(assemble_tool_calls(mixed), [a, b], "交互に届く場合")
    broken = [ToolCallStart("t3", "get_recipe"), ToolCallDelta("t3", '{"recipe_id": "R0')]
    eq(assemble_tool_calls(broken), [BrokenToolCall("t3", "get_recipe", '{"recipe_id": "R0')], "途中で切れた JSON")
    eq(assemble_tool_calls([ToolCallStart("t4", "noop"), ToolCallDelta("t4", "[]")]),
       [BrokenToolCall("t4", "noop", "[]")], "オブジェクトでない JSON")
    eq(assemble_tool_calls([ToolCallStart("t5", "noop")]), [ToolCall("t5", "noop", {})], "断片が無い")
    return f"順に届く・交互に届く（断片 {len(da)} 個と {len(db)} 個）の両方で ToolCallDone と一致・壊れた JSON は BrokenToolCall"


@check("P5 SSE のイベント列だけから、サーバが保存する発言と同じものを組み立て直せる")
async def _():
    fake = FakeProvider(
        fake_script("確認しますね。", tool_calls=[ToolCall("toolu_p1", "get_recipe", {"recipe_id": "R999"})]),
        fake_script("", tool_calls=[ToolCall("toolu_p2", "get_recipe", {"recipe_id": "R001"}),
                                    ToolCall("toolu_p3", "convert_units",
                                             {"amount": 1, "from_unit": "大さじ", "to_unit": "小さじ"})]),
        fake_script("R001 の片栗粉は大さじ1（小さじ3）です。"))
    app.dependency_overrides[get_provider] = lambda: fake
    app.dependency_overrides[get_tool_context] = fixed_context
    try:
        status, events = await post_events(app, {"message": "R001 の片栗粉は小さじでいくつ？"})
    finally:
        app.dependency_overrides.clear()
    eq(status, 200, "status")
    saved = app.state.outcomes[-1].messages
    eq(rebuild_messages(events), saved, "組み立て直した発言")
    eq([m["role"] for m in saved], ["assistant", "user", "assistant", "user", "assistant"], "発言の並び")
    return "assistant → user → assistant（tool_use 2つ）→ user（tool_result 2つ）→ assistant がサーバの保存内容と一致"


@check("P6 同じ引数の呼び直しは実行せず is_error にする（既定値を補った形で比べる）")
async def _():
    executed: list[dict] = []

    def counting(args, ctx) -> dict:
        executed.append(args.model_dump())
        return T.search_recipes(args, ctx)

    base = {**T.TOOLS, "search_recipes": replace(T.TOOLS["search_recipes"], run=counting)}
    fake = FakeProvider(*[fake_script("探します。", tool_calls=[ToolCall(f"toolu_d{i}", "search_recipes", inp)])
                          for i, inp in enumerate([{"ingredients": ["卵"]}, {"limit": 5, "ingredients": ["卵"]},
                                                   {"ingredients": ["卵"]}])])
    chat = ChatRequest(messages=[{"role": "user", "content": "卵のレシピを探して"}])
    events = [ev async for ev in run_tool_loop(fake, chat, fixed_context(), tools=dedup_tools(base),
                                               limits=ToolLimits(max_steps=4))]
    results = [e for e in events if isinstance(e, ToolResult)]
    eq([brief(r) for r in results], ["search_recipes:ok"] + ["search_recipes:error"] * 3, "結果")
    eq([r.output for r in results[1:]], [DUPLICATE.format(name="search_recipes")] * 2 + [STEP_LIMIT], "理由")
    done = events[-1]
    assert isinstance(done, LoopDone)
    eq((len(executed), done.stop_reason), (1, "max_steps"), "実行回数と止まり方")
    return "4 ステップで実行は 1 回・{limit: 5} を足した呼び出しも重複と判定・最後はステップ上限"


class SlowIn(T.ToolInput):
    n: int
    seconds: float


async def _slow(args: SlowIn, ctx) -> dict:
    await asyncio.sleep(args.seconds)
    return {"n": args.n}


@check("P7 並行実行：結果は呼び出しの順・同時実行は2つまで・4つ目以降は実行しない")
async def _():
    tools = {"slow": T.Tool("slow", "待つだけのツール", SlowIn, _slow)}
    calls = [ToolCall(f"toolu_s{i}", "slow", {"n": i, "seconds": s}) for i, s in enumerate([0.2, 0.1, 0.2, 0.1])]
    started = time.perf_counter()
    results = await execute_all(calls, fixed_context(), tools=tools, max_parallel=2, max_calls=3)
    elapsed = time.perf_counter() - started
    eq([r.id for r in results], [c.id for c in calls], "結果の順")
    eq([r.output for r in results[:3]], [{"n": 0}, {"n": 1}, {"n": 2}], "結果の中身")
    eq((results[3].is_error, results[3].output), (True, TOO_MANY.format(max_calls=3)), "4つ目")
    # 上限2なら 0 と 1 が先に動き、1 が終わった 0.1 秒後に 2 が始まる → 約 0.3 秒
    # 上限が無ければ約 0.2 秒、1つずつ順に実行すれば約 0.5 秒になる
    assert 0.28 <= elapsed < 0.45, f"{elapsed:.3f} 秒"
    return "結果は n=0,1,2 の順（終わったのは 1・0・2 の順）・所要は約 0.3 秒（上限なしなら 0.2 秒・順番なら 0.5 秒）・4つ目は is_error"


finish("session08 practice")
