"""Session 8（サーバ側のツール呼び出し）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session08/verify.py
    docker compose exec api bash verify-all.sh src/session08   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import replace

from kondate.verifykit import check, eq, finish
from src.session08.app import app, get_limits, get_provider, get_tool_context
from src.session08.errors import MESSAGES
from src.session08.harness import (PROMPT, brief, call, data_of, fixed_context, fixture_texts, mock_provider,
                                   mock_stats, pairs_ok, post_events, reset_mock, shape)
from src.session08.loop import (STEP_LIMIT, TOOL_FAILED, LoopDone, StepDone, ToolLimits, ToolResult, execute_tool,
                                run_tool_loop)
from src.session08.providers import ChatRequest, FakeProvider, ProviderError, TextDelta, ToolCall, Usage, fake_script
from src.session08.tools import (TOOLS, ConvertUnitsIn, MakeShoppingListIn, SearchRecipesIn, SetTimerIn, Tool,
                                 ToolError, ToolInput, convert_units, make_shopping_list, match_recipes, search_recipes,
                                 set_timer, tool_definitions)

TOOL_NAMES = ["search_recipes", "get_recipe", "convert_units", "set_timer", "make_shopping_list"]
FIXTURE_CALLS = [("search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}),
                 ("get_recipe", {"recipe_id": "R001"})]
NOT_FOUND = "レシピ R999 はありません。search_recipes の結果にある id を指定してください。"


def overrides(**deps) -> None:
    table = {"provider": get_provider, "ctx": get_tool_context, "limits": get_limits}
    app.dependency_overrides.clear()
    for key, value in deps.items():
        app.dependency_overrides[table[key]] = _const(value)


def _const(value):
    # lambda v=value: v と書くと、FastAPI が v をクエリパラメータと見なして既定値を deepcopy し、落ちる
    return lambda: value


@check("V1 5つのツールの定義を、検証に使う Pydantic モデルから作る")
def _():
    defs = tool_definitions()
    eq([d["name"] for d in defs], TOOL_NAMES, "ツール名（plan_week は含めない）")
    eq({d["input_schema"]["type"] for d in defs}, {"object"}, "input_schema.type")
    eq({d["input_schema"].get("additionalProperties") for d in defs}, {False}, "知らない引数は拒否")
    minutes = defs[3]["input_schema"]["properties"]["minutes"]
    eq((minutes["minimum"], minutes["maximum"]), (1, 180), "set_timer.minutes の範囲")
    allergens = defs[0]["input_schema"]["properties"]["exclude_allergens"]["items"]["enum"]
    eq(allergens, ["卵", "乳", "小麦", "えび", "かに", "落花生", "そば"], "exclude_allergens の候補")
    return "5 ツール・additionalProperties: false・minutes は 1〜180・exclude_allergens は7品目の enum"


@check("V2 search_recipes：一致数 → minutes → id の順に決定的に並ぶ（requirements.md の参考値を確定）")
def _():
    ctx = fixed_context()
    args = SearchRecipesIn(ingredients=["鶏むね肉", "キャベツ"], max_minutes=20)
    hits = match_recipes(args, ctx.recipes)
    eq(len(hits), 12, "条件に合う件数")
    eq([(m, r["id"]) for m, r in hits[:5]], [(2, "R001"), (1, "R067"), (1, "R083"), (1, "R112"), (1, "R009")], "上位5件")
    top = search_recipes(args, ctx)["recipes"]
    eq([r["id"] for r in top], ["R001", "R067", "R083", "R112", "R009"], "既定の limit=5 の結果")
    eq(sorted(top[0]), ["id", "kcal", "minutes", "name", "tags"], "1件のキー")
    no_wheat = match_recipes(SearchRecipesIn(ingredients=["鶏むね肉", "キャベツ"], max_minutes=20,
                                             exclude_allergens=["小麦"]), ctx.recipes)
    eq([r["id"] for _, r in no_wheat], ["R001", "R067"], "小麦を除いた結果")
    eq(len(search_recipes(SearchRecipesIn(ingredients=["鶏むね肉", "キャベツ"], max_minutes=20, limit=10), ctx)
           ["recipes"]), 10, "limit=10")
    eq(match_recipes(SearchRecipesIn(ingredients=["キャベツ", "キャベツ"], max_minutes=20), ctx.recipes)[0][0], 1,
       "同じ語を2回送っても一致数は1")
    return "12 件・上位5件 R001（一致2）→ R067・R083・R112・R009（一致1）・小麦を除くと 2 件（R001・R067）・limit=10 で 10 件"


@check("V3 convert_units：Decimal の ROUND_HALF_UP で小数第1位・重さと体積の換算は ToolError")
def _():
    ctx = fixed_context()

    def conv(amount: float, src: str, dst: str) -> dict:
        return convert_units(ConvertUnitsIn(amount=amount, from_unit=src, to_unit=dst), ctx)

    eq(conv(2, "大さじ", "小さじ"), {"amount": 6, "unit": "小さじ"}, "大さじ2 → 小さじ")
    eq(conv(1, "カップ", "大さじ"), {"amount": 13.3, "unit": "大さじ"}, "1カップ → 大さじ")
    eq(conv(0.25, "l", "カップ"), {"amount": 1.3, "unit": "カップ"}, "0.25 l → カップ")
    eq(round(0.25 * 1000 / 200, 1), 1.2, "round() は偶数丸め")
    eq(conv(1.5, "kg", "g"), {"amount": 1500, "unit": "g"}, "1.5 kg → g")
    try:
        conv(1, "大さじ", "g")
        raise AssertionError("ToolError が出ない")
    except ToolError as e:
        eq(str(e), "大さじ と g は換算できません（重さと体積の換算はしません）。", "メッセージ")
    return "大さじ2→小さじ6・1カップ→大さじ13.3・0.25 l→カップ 1.3（round() なら 1.2）・1.5 kg→1500 g・大さじ→g は ToolError"


@check("V4 set_timer：ends_at は注入した時計から計算し、timer_id は timer_ + UUIDv7")
def _():
    ctx = fixed_context()
    out = set_timer(SetTimerIn(minutes=15, label="パスタをゆでる"), ctx)
    eq((out["label"], out["ends_at"]), ("パスタをゆでる", "2026-10-02T18:15:00+09:00"), "label と ends_at")
    assert out["timer_id"].startswith("timer_"), out["timer_id"]
    eq(uuid.UUID(out["timer_id"].removeprefix("timer_")).version, 7, "timer_id の UUID の版")
    ctx.clock.advance(60)
    eq(set_timer(SetTimerIn(minutes=15, label="x"), ctx)["ends_at"], "2026-10-02T18:16:00+09:00", "60秒進めた後")
    return "ends_at=2026-10-02T18:15:00+09:00（FixedClock 18:00 + 15分）・時計を60秒進めると 18:16:00・timer_id は timer_ + UUIDv7"


@check("V5 make_shopping_list：人数で比例換算・家にある食材を除外・同名同単位を合算・name の昇順")
def _():
    ctx = fixed_context()
    one = make_shopping_list(MakeShoppingListIn(recipe_ids=["R001"], servings=1, have=["塩"]), ctx)["items"]
    eq([(i["name"], i["amount"], i["unit"]) for i in one],
       [("こしょう", 0.13, "小さじ"), ("ごま油", 0.5, "大さじ"), ("キャベツ", 100, "g"), ("片栗粉", 0.5, "大さじ"),
        ("鶏がらスープの素", 0.5, "小さじ"), ("鶏むね肉", 125, "g")], "R001 を1人分・塩は家にある")
    eq(round(0.25 * 1 / 2, 2), 0.12, "round() なら 0.12")
    two = {i["name"]: (i["amount"], i["unit"]) for i in
           make_shopping_list(MakeShoppingListIn(recipe_ids=["R001", "R067"]), ctx)["items"]}
    eq((len(two), two["キャベツ"], two["塩"]), (11, (450, "g"), (0.75, "小さじ")), "R001 + R067")
    return "R001 を1人分（塩は家にある）→ 6 品・こしょう 0.13 小さじ（round() なら 0.12）・R001 + R067 → 11 品（キャベツ 450 g・塩 0.75 小さじ）"


async def _boom(args: ToolInput, ctx) -> dict:
    raise RuntimeError("password=hunter2 の DB に接続できません")


async def _slow(args: ToolInput, ctx) -> dict:
    await asyncio.sleep(1.0)
    return {}


@check("V6 execute_tool：どの失敗も例外にせず is_error: true の結果にする")
async def _():
    ctx = fixed_context()
    extra = {**TOOLS, "boom": Tool("boom", "壊れたツール", ToolInput, _boom),
             "slow": Tool("slow", "遅いツール", ToolInput, _slow, timeout_s=0.1)}
    cases = [
        ("存在しないツール", call("delete_recipe", {}), "delete_recipe というツールはありません。"),
        ("存在しない ID", call("get_recipe", {"recipe_id": "R999"}), NOT_FOUND),
        ("ID の形式", call("get_recipe", {"recipe_id": "1"}), "recipe_id:"),
        ("範囲外の分", call("set_timer", {"minutes": 181, "label": "煮込み"}),
         "minutes: Input should be less than or equal to 180"),
        ("知らない引数", call("set_timer", {"minutes": 5, "label": "x", "sound": "bell"}),
         "sound: Extra inputs are not permitted"),
        ("未知のアレルゲン", call("search_recipes", {"ingredients": ["豆腐"], "exclude_allergens": ["ごま"]}),
         "exclude_allergens.0:"),
        ("重さ⇔体積", call("convert_units", {"amount": 1, "from_unit": "大さじ", "to_unit": "g"}), "換算できません"),
        ("想定外の例外", call("boom", {}), TOOL_FAILED),
        ("タイムアウト", call("slow", {}), "slow が 0.1 秒以内に終わりませんでした。"),
    ]
    for label, c, expected in cases:
        r = await execute_tool(c, ctx, tools=extra)
        eq(r.is_error, True, f"{label}: is_error")
        assert isinstance(r.output, str) and expected in r.output, f"{label}: {r.output!r}"
        assert "hunter2" not in r.output, r.output
    big = await execute_tool(call("get_recipe", {"recipe_id": "R001"}), ctx, limits=ToolLimits(max_output_chars=200))
    eq((big.is_error, big.output.startswith("get_recipe の結果が大きすぎます")), (True, True), "出力サイズ上限")
    ok = await execute_tool(call("get_recipe", {"recipe_id": "R001"}), ctx)
    eq((ok.is_error, ok.output["name"]), (False, "鶏むね肉とキャベツの塩炒め"), "成功")
    return f"{len(cases) + 1} 種類の失敗がすべて is_error: true（例外の文は出さない）・R001 は成功"


@check("V7 run_tool_loop（Fake）：ツールの失敗を LLM に返し、LLM が直して続ける")
async def _():
    fake = FakeProvider(
        fake_script("確認しますね。", tool_calls=[ToolCall("toolu_f1", "get_recipe", {"recipe_id": "R999"})],
                    usage=Usage(100, 10)),
        fake_script("", tool_calls=[ToolCall("toolu_f2", "get_recipe", {"recipe_id": "R001"})], usage=Usage(200, 10)),
        fake_script("R001 は15分で作れます。", usage=Usage(300, 20)))
    chat = ChatRequest(messages=[{"role": "user", "content": "鶏むね肉の炒め物の作り方は？"}])
    events = [ev async for ev in run_tool_loop(fake, chat, fixed_context())]
    eq([brief(e) for e in events if isinstance(e, ToolResult)], ["get_recipe:error", "get_recipe:ok"], "結果")
    eq([e.stop_reason for e in events if isinstance(e, StepDone)], ["tool_use", "tool_use", "end_turn"], "各ステップ")
    done = events[-1]
    assert isinstance(done, LoopDone)
    eq((done.stop_reason, done.steps, done.usage), ("end_turn", 3, Usage(600, 40)), "LoopDone")
    eq(fake.requests[1].messages[-1], {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_f1", "content": NOT_FOUND, "is_error": True}]}, "2回目の要求の末尾")
    eq([[t["name"] for t in r.tools] for r in fake.requests], [TOOL_NAMES] * 3, "毎回同じツール定義を送る")
    eq(([m["role"] for m in done.messages], pairs_ok(done.messages)),
       (["assistant", "user", "assistant", "user", "assistant"], True), "増えた発言")
    return ("R999 → is_error → R001 → ok → end_turn・LLM 呼び出し 3 回・usage は合計（600 / 40）・"
            "増えた発言 5 件（tool_use と tool_result は組のまま）")


async def run_mock(name: str) -> tuple[list[dict], dict]:
    await reset_mock()
    async with mock_provider(name) as p:
        overrides(provider=p, ctx=fixed_context())
        try:
            status, events = await post_events(app, {"message": PROMPT})
        finally:
            app.dependency_overrides.clear()
    eq(status, 200, "status")
    return events, await mock_stats()


def expected_shape() -> str:
    n = [math.ceil(len(t) / 6) for t in fixture_texts()]  # mockllm は text_delta を6文字ずつ送る
    return (f"start → delta×{n[0]} → tool_call → tool_result → delta×{n[1]} → tool_call → tool_result → "
            f"delta×{n[2]} → usage → done")


@check("V8 mockllm（kondate_tool_search）：search_recipes → get_recipe → 最終回答をストリーミングで届ける")
async def _():
    events, stats = await run_mock("anthropic")
    eq(shape(events), expected_shape(), "イベント列")
    calls = data_of(events, "tool_call")
    eq([(c["name"], c["input"]) for c in calls], FIXTURE_CALLS, "tool_call")
    results = data_of(events, "tool_result")
    eq([(r["id"], r["is_error"]) for r in results], [(c["id"], False) for c in calls], "tool_result の id と is_error")
    eq([x["id"] for x in results[0]["output"]["recipes"]], ["R001", "R067", "R083", "R112", "R009"], "検索結果")
    eq(results[1]["output"]["name"], "鶏むね肉とキャベツの塩炒め", "get_recipe の結果")
    eq("".join(d["text"] for d in data_of(events, "delta")), "".join(fixture_texts()), "delta をつないだ文")
    reqs = [r for r in stats["requests"] if r["path"] == "/v1/messages"]
    eq([(r["scenario"], r["step"], r["stop_reason"]) for r in reqs],
       [("kondate_tool_search", 0, "tool_use"), ("kondate_tool_search", 1, "tool_use"),
        ("kondate_tool_search", 2, "end_turn")], "mockllm の記録")
    eq(data_of(events, "usage"), [{"input_tokens": sum(r["input_tokens"] for r in reqs),
                                   "output_tokens": sum(r["output_tokens"] for r in reqs)}], "usage は3回の合計")
    eq(data_of(events, "done"), [{"stop_reason": "end_turn"}], "done")
    o = app.state.outcomes[-1]
    eq((o.reason, o.steps, o.tools, pairs_ok(o.messages)),
       ("completed", 3, ["search_recipes:ok", "get_recipe:ok"], True), "結末")
    return f"{shape(events)}・mockllm のステップ 0 → 1 → 2・usage は3回の合計と一致"


@check("V9 openai 互換の上流でも、同じイベント列と同じツール呼び出しになる")
async def _():
    events, _ = await run_mock("openai")
    eq(shape(events), expected_shape(), "イベント列")
    eq([(c["name"], c["input"]) for c in data_of(events, "tool_call")], FIXTURE_CALLS, "tool_call")
    eq(data_of(events, "done"), [{"stop_reason": "end_turn"}], "done")
    return "anthropic と同じイベント列・同じ2つの tool_call"


@check("V10 ステップ上限：ツールを呼び続ける LLM を3回で止め、最後の呼び出しは実行せずに組を閉じる")
async def _():
    executed: list[str] = []

    def counting(args: SearchRecipesIn, ctx) -> dict:
        executed.append("search_recipes")
        return search_recipes(args, ctx)

    tools = {**TOOLS, "search_recipes": replace(TOOLS["search_recipes"], run=counting)}
    fake = FakeProvider(fake_script("もう一度探します。", usage=Usage(50, 5),
                                    tool_calls=[ToolCall("toolu_loop", "search_recipes", {"ingredients": ["卵"]})]))
    chat = ChatRequest(messages=[{"role": "user", "content": "卵のレシピを探して"}])
    events = [ev async for ev in run_tool_loop(fake, chat, fixed_context(), tools=tools,
                                               limits=ToolLimits(max_steps=3))]
    done = events[-1]
    assert isinstance(done, LoopDone)
    results = [e for e in events if isinstance(e, ToolResult)]
    eq((done.stop_reason, done.steps, len(fake.requests), len(executed)), ("max_steps", 3, 3, 2), "止まり方")
    eq([brief(r) for r in results], ["search_recipes:ok", "search_recipes:ok", "search_recipes:error"], "結果")
    eq(results[-1].output, STEP_LIMIT, "最後の結果")
    eq((len(done.messages), pairs_ok(done.messages), done.usage), (6, True, Usage(150, 15)), "発言と usage")
    return "LLM 呼び出し 3 回で max_steps・実行は 2 回・3回目は is_error（実行しない）で組を閉じる・増えた発言 6 件"


@check("V11 途中で上流が失敗したら error で終える（ツールの失敗は tool_result の is_error で返す）")
async def _():
    fake = FakeProvider(
        fake_script("探しますね。", tool_calls=[ToolCall("toolu_e1", "get_recipe", {"recipe_id": "R999"})]),
        [TextDelta("作り方は"), ProviderError("overloaded", provider="fake")])
    overrides(provider=fake, ctx=fixed_context())
    try:
        status, events = await post_events(app, {"message": "R999 の作り方は？"})
    finally:
        app.dependency_overrides.clear()
    eq((status, shape(events)), (200, "start → delta → tool_call → tool_result → delta → error"), "イベント列")
    eq(data_of(events, "tool_result"), [{"id": "toolu_e1", "output": NOT_FOUND, "is_error": True}], "tool_result")
    err = data_of(events, "error")[0]
    eq((err["type"], err["message"]), ("upstream_unavailable", MESSAGES["upstream_unavailable"]), "error")
    eq(err["request_id"], app.state.outcomes[-1].request_id, "request_id")
    return "start → delta → tool_call → tool_result（is_error）→ delta → error（upstream_unavailable）・usage と done は送らない"


@check("V12 ストリーム開始前の検証エラーは JSON の 422 で返り、上流は呼ばれない")
async def _():
    fake = FakeProvider(fake_script("呼ばれないはず"))
    overrides(provider=fake, ctx=fixed_context())
    try:
        status, body = await post_events(app, {"message": ""})
    finally:
        app.dependency_overrides.clear()
    eq((status, body[0]["error"]["type"], fake.requests), (422, "invalid_request", []), "422")
    return "空の message → 422 invalid_request（ストリームは始まらず、上流も呼ばない）"


finish("session08")
