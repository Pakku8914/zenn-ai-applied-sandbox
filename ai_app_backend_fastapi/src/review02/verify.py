"""復習2（セッション2〜8の横断復習）の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review02

DB はスキーマ review02、Redis はキー接頭辞 review02: だけを使い、冒頭で作り直す。
"""

from __future__ import annotations

import asyncio
import json
import math

import httpx2
from sqlalchemy import delete
from uuid_utils import uuid7

from kondate.db import SessionLocal
from kondate.verifykit import check, eq, finish
from src.review02.app import SYSTEM, app
from src.review02.errors import MESSAGES
from src.review02.harness import (PROMPT, asgi_client, count_rows, data_of, dbcheck, events_of, fixed_context,
                                  fixture_texts, mock_provider, new_conversation, prepare, read_until, replay_keys,
                                  reset_mock, serve, shape, wait_until, wired)
from src.review02.loop import TOOL_FAILED, ToolResult, run_tool_loop
from src.review02.models import Conversation
from src.review02.providers import (ChatRequest, Done, FakeProvider, ProviderError, TextDelta, ToolCall, Usage,
                                    fake_script, normalize_anthropic_stream, normalize_openai_stream)
from src.review02.q3_recover import recover
from src.review02.q4_order import (anthropic_events, call_order, calls_from_done, naive_tool_calls, openai_chunks,
                                   replay)
from src.review02.relay import prime_loop
from src.review02.resume import events_key, load_replay
from src.review02.tools import TOOLS, Tool, ToolInput

PORT = 18722
FIRST_TEXT = "探しますね。"  # 6文字 → delta 1個（fake_script は6文字ずつ切る）
FAKE_TEXT = "鶏むね肉とキャベツの塩炒めがおすすめです。"  # 21文字 → delta 4個
NOT_FOUND = "レシピ R999 はありません。search_recipes の結果にある id を指定してください。"
TOOL_NAMES = ["search_recipes", "get_recipe", "convert_units", "set_timer", "make_shopping_list"]
FIXTURE_CALLS = [("search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}),
                 ("get_recipe", {"recipe_id": "R001"})]
R001 = ToolCall("toolu_r001", "get_recipe", {"recipe_id": "R001"})
R999 = ToolCall("toolu_r999", "get_recipe", {"recipe_id": "R999"})
WITH_TOOL = "start → delta → tool_call → tool_result → delta×4 → usage → done"

asyncio.run(prepare())


def url(cid: str) -> str:
    return f"/api/conversations/{cid}/messages"


def two_steps(call: ToolCall, second: list | None = None) -> FakeProvider:
    """1回目は FIRST_TEXT を書いてから call を呼び、2回目は FAKE_TEXT で答える（second で差し替えられる）。"""
    return FakeProvider(fake_script(FIRST_TEXT, tool_calls=[call], usage=Usage(100, 10)),
                        second or fake_script(FAKE_TEXT, usage=Usage(150, 20)))


class DeletingProvider:
    """最後の Done を返す直前に会話を消す（ストリーミング中に別のタブで会話が削除された状況）。"""

    name = "fake"

    def __init__(self, inner: FakeProvider, conversation_id: str) -> None:
        self.inner, self.conversation_id = inner, conversation_id

    async def complete(self, req):
        return await self.inner.complete(req)

    async def stream(self, req):
        async for ev in self.inner.stream(req):
            if isinstance(ev, Done):
                async with SessionLocal() as s:
                    await s.execute(delete(Conversation).where(Conversation.id == self.conversation_id))
                    await s.commit()
            yield ev


async def _boom(args: ToolInput, ctx) -> dict:
    raise RuntimeError("password=hunter2 の DB に接続できません")


async def _wait_a_bit(args: ToolInput, ctx) -> dict:
    await asyncio.sleep(1.0)
    return {"waited": True}


async def run_row(provider, *, body: dict | None = None, cid: str | None = None, tools=None) -> dict:
    """1往復を送り、結末（HTTP・種別・イベント列・保存した行・再送の状態）をまとめる。"""
    cid = cid or await new_conversation()
    async with wired(app, provider, tools=tools), asgi_client(app) as c:
        r = await c.post(url(cid), json=body or {"content": PROMPT})
        events = events_of(r.text) if r.status_code == 200 else []
        replay_status = None
        if events:
            replay_status = (await c.get(f"/api/chat/stream/{events[0]['data']['message_id']}")).status_code
    if r.status_code != 200:
        type_ = r.json()["error"]["type"]
    else:
        type_ = events[-1]["data"]["type"] if events[-1]["event"] == "error" else None
    return {"status": r.status_code, "type": type_, "shape": shape(events) if events else None,
            "rows": await count_rows(cid), "replay": replay_status, "headers": r.headers, "events": events}


@dbcheck("R1 問題1：8つの状況の結末（HTTP・イベント列・保存した行・再送・上流の呼び出し回数）")
async def _():
    boom = {**TOOLS, "boom": Tool("boom", "壊れたツール", ToolInput, _boom)}
    limited = ProviderError("rate_limited", provider="fake", status_code=429, retry_after=2)
    overloaded = ProviderError("overloaded", provider="fake", status_code=529)
    cases: dict[int, tuple[dict, FakeProvider]] = {}

    fake = FakeProvider(fake_script("呼ばれないはず"))
    cases[1] = (await run_row(fake, body={"content": ""}), fake)
    fake = FakeProvider(fake_script("呼ばれないはず"))
    cases[2] = (await run_row(fake, cid=str(uuid7())), fake)
    fake = FakeProvider([limited])
    cases[3] = (await run_row(fake), fake)
    fake = FakeProvider([ProviderError("timeout", provider="fake")])
    cases[4] = (await run_row(fake), fake)
    fake = two_steps(R999)
    cases[5] = (await run_row(fake), fake)
    fake = two_steps(R001, [TextDelta("作り方は"), overloaded])
    cases[6] = (await run_row(fake), fake)
    fake = two_steps(ToolCall("toolu_boom", "boom", {}))
    cases[7] = (await run_row(fake, tools=boom), fake)
    cid = await new_conversation()
    inner = FakeProvider(fake_script(FAKE_TEXT, usage=Usage(150, 20)))
    cases[8] = (await run_row(DeletingProvider(inner, cid), cid=cid), inner)

    got = {n: (row["status"], row["type"], row["shape"], row["rows"], row["replay"], len(f.requests))
           for n, (row, f) in cases.items()}
    eq(got, {
        1: (422, "invalid_request", None, 0, None, 0),
        2: (404, "not_found", None, 0, None, 0),
        3: (429, "rate_limited", None, 0, None, 1),
        4: (504, "upstream_timeout", None, 0, None, 1),
        5: (200, None, WITH_TOOL, 4, 200, 2),
        6: (200, "upstream_unavailable", "start → delta → tool_call → tool_result → delta → error", 0, 200, 2),
        7: (200, None, WITH_TOOL, 4, 200, 2),
        8: (200, "internal_error", "start → delta×4 → error", 0, 200, 1),
    }, "(HTTP, error.type, イベント列, 保存した行, 再送, 上流の呼び出し)")
    eq(cases[3][0]["headers"]["retry-after"], "2", "行3の retry-after")
    eq("retry-after" in cases[4][0]["headers"], False, "行4に retry-after は付かない")
    eq(data_of(cases[5][0]["events"], "tool_result"), [{"id": "toolu_r999", "output": NOT_FOUND, "is_error": True}],
       "行5の tool_result")
    eq(data_of(cases[7][0]["events"], "tool_result")[0]["output"], TOOL_FAILED, "行7の tool_result")
    assert "hunter2" not in json.dumps(cases[7][0]["events"], ensure_ascii=False)
    return ("1 → 422 invalid_request・2 → 404 not_found・3 → 429 rate_limited（retry-after: 2）・"
            "4 → 504 upstream_timeout（どれもストリームは始まらない）／5・7 → done まで届き 4 行保存／"
            "6 → error（upstream_unavailable）・8 → error（internal_error）で 0 行・5〜8 の再送は 200")


@dbcheck("R2 問題2：ツールの実行中に切断すると、何も保存せず、2回目の LLM 呼び出しもしない")
async def _():
    cid = await new_conversation()
    tools = {**TOOLS, "wait_a_bit": Tool("wait_a_bit", "1秒かかるツール", ToolInput, _wait_a_bit)}
    fake = two_steps(ToolCall("toolu_wait", "wait_a_bit", {}))
    before = len(app.state.outcomes)
    async with wired(app, fake, tools=tools) as redis, serve(app, PORT) as base:
        async with httpx2.AsyncClient(timeout=30) as c:
            got = await read_until(c, f"{base}{url(cid)}", {"content": PROMPT}, "tool_call")
        await wait_until(lambda: len(app.state.outcomes) > before, 5.0, "後始末が終わらない")
        o = app.state.outcomes[-1]
        replayed = await load_replay(redis, o.message_id, 0)
    assert o.reason in ("client_disconnected", "cancelled"), o.reason
    eq(shape(got), "start → delta → tool_call", "クライアントが受け取ったイベント")
    eq((await count_rows(cid), o.saved, len(fake.requests)), (0, False, 1), "保存した行・保存・上流の呼び出し")
    eq((o.steps, o.step_in_progress, o.usage), (1, False, Usage(100, 10)), "usage")
    eq(replayed, None, "再送")
    return ("受け取ったのは start → delta → tool_call・保存 0 行・LLM 呼び出し 1 回・"
            "usage は1回目の上流の値（100 / 10）・再送は 204（控えが done も error も持たない）")


@dbcheck("R3 問題3：取りこぼしは控え（Redis）で埋め、控えが無ければ DB の発言を正とする")
async def _():
    cid = await new_conversation()
    async with wired(app, two_steps(R001)) as redis, asgi_client(app) as c:
        events = events_of((await c.post(url(cid), json={"content": PROMPT})).text)
        mid = events[0]["data"]["message_id"]
        tail = await recover(c, cid, mid, 8)
        await redis.ltrim(events_key(mid), 0, 7)  # 保存のあと、usage を送る前に切れたのと同じ控えにする
        cut = await recover(c, cid, mid, 8)
        await redis.delete(events_key(mid))  # TTL が切れたのと同じ
        expired = await recover(c, cid, mid, 8)
        lost = await recover(c, cid, str(uuid7()), 0)
    eq([e["id"] for e in events], [str(i) for i in range(1, 11)], "id")
    eq((tail.source, [(e["id"], e["event"]) for e in tail.events]), ("replay", [("9", "usage"), ("10", "done")]),
       "取りこぼした末尾")
    eq((cut.source, expired.source, lost.source), ("history", "history", "lost"), "控えが無いとき")
    eq((cut.message["id"], cut.message["content"]), (mid, [{"type": "text", "text": FAKE_TEXT}]), "DB の発言")
    eq("".join(d["text"] for d in data_of(events[4:8], "delta")), FAKE_TEXT, "控えの delta と DB の text")
    return ("id 1〜10・Last-Event-ID: 8 → 控えから usage・done（id 9・10）／控えが途中まで → 204 → DB の発言"
            "（id は start の message_id）／控えが期限切れ → DB の発言／保存されていない ID → lost")


@check("R4 問題4：ツールの差分の届き方は違っても、ToolCallDone とループの結果はそろう")
async def _():
    a = ToolCall("toolu_o1", "search_recipes", {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20})
    b = ToolCall("toolu_o2", "get_recipe", {"recipe_id": "R001"})
    ant = [e async for e in normalize_anthropic_stream(replay(anthropic_events("探します。", [a, b])))]
    oai = [e async for e in normalize_openai_stream(replay(openai_chunks("探します。", [a, b])))]
    eq(call_order(ant), ["start:toolu_o1", "done:toolu_o1", "start:toolu_o2", "done:toolu_o2"], "Anthropic の順序")
    eq(call_order(oai), ["start:toolu_o1", "start:toolu_o2", "done:toolu_o1", "done:toolu_o2"], "OpenAI 互換の順序")
    eq((calls_from_done(ant), calls_from_done(oai)), ([a, b], [a, b]), "ToolCallDone")
    eq((ant[-1], oai[-1]), (Done("tool_use", Usage(100, 30)), Done("tool_use", Usage(100, 30))), "Done")
    raw_a, raw_b = (json.dumps(c.input, ensure_ascii=False) for c in (a, b))
    eq(naive_tool_calls(ant), [("toolu_o1", raw_a), ("toolu_o2", raw_b)], "id を見ない組み立て（Anthropic）")
    broken = naive_tool_calls(oai)
    eq((broken[0], broken[1][1] == raw_b), (("toolu_o1", ""), False), "id を見ない組み立て（OpenAI 互換）")
    results = {}
    for label, script in (("anthropic", ant), ("openai", oai)):
        fake = FakeProvider(script, fake_script("どちらも調べました。"))
        chat = ChatRequest(messages=[{"role": "user", "content": PROMPT}])
        evs = [e async for e in run_tool_loop(fake, chat, fixed_context())]
        results[label] = [(r.id, r.name, r.is_error) for r in evs if isinstance(r, ToolResult)]
    eq(results["anthropic"], results["openai"], "ループの結果")
    eq(results["openai"], [("toolu_o1", "search_recipes", False), ("toolu_o2", "get_recipe", False)], "ツールの結果")
    return ("Anthropic は start → done を1つずつ・OpenAI 互換は start×2 → done×2／ToolCallDone・"
            "Done（tool_use・100 / 30）・ループの結果は同じ／id を見ない組み立ては交互に届くと壊れる")


@dbcheck("R5 問題5：1回目の失敗だけが JSON になり、2回目以降の失敗は error イベントになる")
async def _():
    fake = two_steps(R001)
    primed = await prime_loop(fake, ChatRequest(messages=[{"role": "user", "content": PROMPT}]), fixed_context())
    first, calls = primed.first, len(fake.requests)
    await primed.events.aclose()
    eq((first, calls), (TextDelta(FIRST_TEXT), 1), "先読みで読んだもの")
    limited = ProviderError("rate_limited", provider="fake", status_code=429, retry_after=3)
    before = await replay_keys()
    early = await run_row(FakeProvider([limited]))
    after_early = await replay_keys()
    late = await run_row(two_steps(R001, [limited]))
    eq((early["status"], early["type"], early["headers"]["retry-after"], after_early - before),
       (429, "rate_limited", "3", 0), "1回目で 429")
    eq((late["status"], late["shape"], late["type"], "retry-after" in late["headers"], late["rows"]),
       (200, "start → delta → tool_call → tool_result → error", "rate_limited", False, 0), "2回目で 429")
    err = data_of(late["events"], "error")[0]
    eq((sorted(err), err["message"]), (["message", "request_id", "type"], MESSAGES["rate_limited"]), "error の中身")
    return ("先読みで読むのは1回目の最初の TextDelta（上流 1 回）／1回目の 429 → 429 JSON（retry-after: 3・控えなし）／"
            "2回目の 429 → 200 のまま start → delta → tool_call → tool_result → error（rate_limited・retry-after なし）・0 行")


@dbcheck("R6 問題6：保存してから usage と done を送り、次の往復では保存した発言を履歴として送る")
async def _():
    cid = await new_conversation()
    fake = FakeProvider(fake_script(FIRST_TEXT, tool_calls=[R001], usage=Usage(100, 10)),
                        fake_script(FAKE_TEXT, usage=Usage(150, 20)),
                        fake_script("副菜はわかめスープにしましょう。", usage=Usage(300, 15)))
    async with wired(app, fake), asgi_client(app) as c:
        first = events_of((await c.post(url(cid), json={"content": PROMPT})).text)
        second = events_of((await c.post(url(cid), json={"content": "副菜も考えて"})).text)
        detail = (await c.get(f"/api/conversations/{cid}")).json()
    eq((shape(first), shape(second)), (WITH_TOOL, "start → delta×3 → usage → done"), "イベント列")
    eq([e["id"] for e in first], [str(i) for i in range(1, 11)], "id は 1 から順に")
    eq(data_of(first, "usage"), [{"input_tokens": 250, "output_tokens": 30}], "usage は2回の合計")
    msgs = detail["messages"]
    eq([(m["seq"], m["role"]) for m in msgs],
       [(1, "user"), (2, "assistant"), (3, "user"), (4, "assistant"), (5, "user"), (6, "assistant")], "保存した発言")
    eq({m["status"] for m in msgs}, {"complete"}, "status")
    eq((msgs[3]["id"], msgs[5]["id"]), (first[0]["data"]["message_id"], second[0]["data"]["message_id"]),
       "最後の assistant の ID")
    eq(([b["type"] for b in msgs[1]["content"]], msgs[2]["content"][0]["tool_use_id"]),
       (["text", "tool_use"], R001.id), "tool_use と tool_result の組")
    nxt = fake.requests[2]
    eq(nxt.messages[:4], [{"role": m["role"], "content": m["content"]} for m in msgs[:4]], "履歴は DB の中身そのもの")
    eq((len(nxt.messages), nxt.system == SYSTEM, [t["name"] for t in nxt.tools]), (5, True, TOOL_NAMES),
       "2往復目の1回目の要求")
    return ("1往復目 start → delta → tool_call → tool_result → delta×4 → usage → done（usage 250 / 30）・"
            "2往復目 start → delta×3 → usage → done／保存 6 行（seq 1〜6・complete）・"
            "最後の assistant の ID は start の message_id・2往復目の要求に保存した4件をそのまま送る")


@dbcheck("R7 mockllm（kondate_tool_search）でも、同じ順で中継して6件を保存する")
async def _():
    await reset_mock()
    cid = await new_conversation()
    async with mock_provider() as p, wired(app, p), asgi_client(app) as c:
        events = events_of((await c.post(url(cid), json={"content": PROMPT})).text)
        detail = (await c.get(f"/api/conversations/{cid}")).json()
    n = [math.ceil(len(t) / 6) for t in fixture_texts()]  # mockllm は text_delta を6文字ずつ送る
    eq(shape(events), f"start → delta×{n[0]} → tool_call → tool_result → delta×{n[1]} → tool_call → tool_result → "
                      f"delta×{n[2]} → usage → done", "イベント列")
    eq([(x["name"], x["input"]) for x in data_of(events, "tool_call")], FIXTURE_CALLS, "tool_call")
    eq([m["role"] for m in detail["messages"]], ["user", "assistant", "user", "assistant", "user", "assistant"],
       "保存した発言")
    eq((detail["messages"][-1]["id"], events[-1]["id"]), (events[0]["data"]["message_id"], str(len(events))),
       "最後の assistant の ID と id の数")
    return f"{shape(events)}・保存した発言 6 件（最後の assistant の ID は start の message_id）"


finish("review02")
