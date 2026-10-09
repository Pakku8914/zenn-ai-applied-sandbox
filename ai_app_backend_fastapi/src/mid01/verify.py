"""中間プロジェクト1（献立相談チャット API）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/mid01/verify.py
    docker compose exec api bash verify-all.sh src/mid01

スキーマ mid01 を作り直してから、正常系と異常系の振る舞い表を1行ずつ確かめる。
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid

from uuid_utils import uuid7

from kondate.db import SessionLocal
from kondate.verifykit import eq, finish
from src.mid01 import repo
from src.mid01.app import SYSTEM, TOO_LONG_MESSAGE, app
from src.mid01.errors import MESSAGES
from src.mid01.harness import (FIXTURE_CALLS, PORT, PROMPT, ROOT, PausingProvider, alembic, alternates,
                               as_messages, asgi_client, data_of, dbcheck, expected_shape, fetch, fixture_texts,
                               mock_llm, mock_stats, new_conversation, pairs_ok, post_message, read_until,
                               reset_mock, reset_schema, rows_of, serve, shape, stored, tool_turn, upgraded,
                               wait_until, wired)
from src.mid01.history import (INTERRUPTED_NOTE, flatten, for_model, note_message, split_groups,
                               with_new_user)
from src.mid01.loop import STEP_LIMIT, ToolLimits
from src.mid01.models import Message
from src.mid01.providers import FakeProvider, ProviderError, TextDelta, ToolCall, fake_script
from src.mid01.tokens import ApproxTokenCounter
from src.mid01.turn import STEP_LIMIT_NOTE, StoredMessage

TOOL_NAMES = ["search_recipes", "get_recipe", "convert_units", "set_timer", "make_shopping_list"]
NOT_FOUND = "レシピ R999 はありません。search_recipes の結果にある id を指定してください。"
COMPLETE_6 = [("user", "complete", None), ("assistant", "complete", "tool_use"), ("user", "complete", None),
              ("assistant", "complete", "tool_use"), ("user", "complete", None), ("assistant", "complete", "end_turn")]


def text(t: str) -> list[dict]:
    return [{"type": "text", "text": t}]


@dbcheck("V1 Alembic：upgrade head で 0001 → 0002 を当て、表も版の記録もスキーマ mid01 に置く")
async def _():
    await reset_schema()
    log = alembic("upgrade", "head")
    eq(upgraded(log), ["0001", "0002"], "当たった版")
    tables = await fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'mid01' ORDER BY 1")
    eq(tables, ["alembic_version", "conversations", "messages"], "mid01 の表")
    eq(await fetch("SELECT version_num FROM mid01.alembic_version"), ["0002"], "版の記録")
    cols = await fetch("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = 'mid01' AND table_name = 'messages' ORDER BY ordinal_position")
    eq(cols, ["id", "conversation_id", "seq", "role", "content", "status", "created_at", "stop_reason"], "列")
    eq(upgraded(alembic("downgrade", "0001")), ["0001"], "0001 へ戻す")
    eq(await fetch("SELECT count(*) FROM information_schema.columns "
                   "WHERE table_schema = 'mid01' AND column_name = 'stop_reason'"), [0], "戻したあとの stop_reason")
    eq(upgraded(alembic("upgrade", "head")), ["0002"], "もう一度 head へ")
    return "0001 → 0002・表は alembic_version / conversations / messages・stop_reason は 0002 で足した列（0001 へ戻すと消える）"


@dbcheck("V2 会話の作成と取得：持ち主は u001・本文の user_id は 422・知らない会話は上流を呼ばずに 404")
async def _():
    fake = FakeProvider(fake_script("呼ばれないはず"))
    with wired(app, fake):
        async with asgi_client(app) as c:
            r = await c.post("/api/conversations", json={"title": "今夜の献立"})
            bad = await c.post("/api/conversations", json={"user_id": "u002"})
            detail = (await c.get(f"/api/conversations/{r.json()['id']}")).json()
            missing = await c.get(f"/api/conversations/{uuid7()}")
            post_missing = await c.post(f"/api/conversations/{uuid7()}/messages", json={"content": PROMPT})
            bad_id = await c.get("/api/conversations/abc")
    body = r.json()
    eq((r.status_code, body["user_id"], body["title"]), (201, "u001", "今夜の献立"), "作成")
    eq(uuid.UUID(body["id"]).version, 7, "会話 ID の版")
    eq((bad.status_code, bad.json()["error"]["type"]), (422, "invalid_request"), "本文の user_id")
    eq(detail["messages"], [], "作った直後の発言")
    for res in (missing, post_missing):
        eq((res.status_code, res.json()["error"]["type"], res.json()["error"]["message"]),
           (404, "not_found", MESSAGES["not_found"]), "知らない会話")
    eq((fake.requests, bad_id.status_code), ([], 422), "上流の呼び出しと ID の形式")
    return "201・user_id は u001（本文の user_id は 422）・知らない会話は GET も POST も 404 not_found・上流は呼ばない"


@dbcheck("V3 mockllm（kondate_tool_search）：ツールの進行を流し、6件の発言を保存してから done を送る")
async def _():
    await reset_mock()
    async with mock_llm() as (provider, counter):
        with wired(app, provider, counter=counter):
            async with asgi_client(app) as c:
                cid = await new_conversation(c)
                r, events = await post_message(c, cid, PROMPT)
                saved = await stored(c, cid)
    stats = await mock_stats()
    eq((r.status_code, shape(events)), (200, expected_shape()), "イベント列")
    eq([(x["name"], x["input"]) for x in data_of(events, "tool_call")], FIXTURE_CALLS, "tool_call")
    eq(data_of(events, "done"), [{"stop_reason": "end_turn"}], "done")
    eq(rows_of(saved), COMPLETE_6, "保存した発言（role・status・stop_reason）")
    eq([m["seq"] for m in saved], [1, 2, 3, 4, 5, 6], "seq")
    eq(saved[-1]["id"], events[0]["data"]["message_id"], "start の message_id")
    eq(saved[-1]["content"], text(fixture_texts()[2]), "最後の発言")
    eq(pairs_ok(as_messages(saved)), True, "tool_use と tool_result の組")
    reqs = [x for x in stats["requests"] if x["path"] == "/v1/messages"]
    eq([(x["scenario"], x["step"]) for x in reqs], [("kondate_tool_search", s) for s in (0, 1, 2)], "mockllm")
    return f"{shape(events)}・保存は seq 1〜6（最後の assistant の ID が start の message_id）・mockllm のステップ 0 → 1 → 2"


@dbcheck("V4 2往復目：保存した履歴（tool_use と tool_result の組）を付けて LLM を呼ぶ")
async def _():
    fake = FakeProvider(*tool_turn("toolu_h1"), fake_script("どういたしまして。"))
    with wired(app, fake):
        async with asgi_client(app) as c:
            cid = await new_conversation(c)
            await post_message(c, cid, "R001 の作り方は？")
            r, events = await post_message(c, cid, "ありがとう")
            saved = await stored(c, cid)
    sent = fake.requests[2]
    eq([m["role"] for m in sent.messages], ["user", "assistant", "user", "assistant", "user"], "2往復目に送った messages")
    eq((sent.messages[-1]["content"], sent.system), (text("ありがとう"), SYSTEM), "新しい発言と system")
    eq([t["name"] for t in sent.tools], TOOL_NAMES, "毎回同じツール定義")
    eq(([m["seq"] for m in saved], alternates(saved), pairs_ok(as_messages(saved))),
       ([1, 2, 3, 4, 5, 6], True, True), "保存した発言")
    return "2往復目の要求に履歴 4 件＋新しい発言・保存は seq 1〜6（user と assistant が交互・組は分断しない）"


@dbcheck("V5 ツールの失敗：is_error の tool_result も往復の一部として complete で保存する")
async def _():
    fake = FakeProvider(
        fake_script("確認しますね。", tool_calls=[ToolCall("toolu_e1", "get_recipe", {"recipe_id": "R999"})]),
        fake_script("", tool_calls=[ToolCall("toolu_e2", "get_recipe", {"recipe_id": "R001"})]),
        fake_script("R001 は15分で作れます。"))
    with wired(app, fake):
        async with asgi_client(app) as c:
            cid = await new_conversation(c)
            r, events = await post_message(c, cid, "R999 の作り方は？")
            saved = await stored(c, cid)
    eq(shape(events), "start → delta×2 → tool_call → tool_result → tool_call → tool_result → delta×3 → usage → done",
       "イベント列")
    eq([x["is_error"] for x in data_of(events, "tool_result")], [True, False], "tool_result の is_error")
    eq(rows_of(saved), COMPLETE_6, "保存した発言")
    eq(saved[2]["content"], [{"type": "tool_result", "tool_use_id": "toolu_e1", "content": NOT_FOUND,
                              "is_error": True}], "保存した失敗の結果")
    return f"{shape(events)}・is_error: true の結果も complete のまま保存（LLM が直して続けた）"


@dbcheck("V6 ステップ上限：done は max_steps・締めの assistant で往復を閉じ、次の往復で user を2つ続けない")
async def _():
    loop_fake = FakeProvider(fake_script("もう一度探します。",
                                         tool_calls=[ToolCall("toolu_m1", "search_recipes", {"ingredients": ["卵"]})]))
    next_fake = FakeProvider(fake_script("条件を変えて探しますね。"))
    async with asgi_client(app) as c:
        cid = await new_conversation(c)
        with wired(app, loop_fake, limits=ToolLimits(max_steps=2)):
            r, events = await post_message(c, cid, "卵のレシピを探して")
        with wired(app, next_fake):
            await post_message(c, cid, "20分以内でお願い")
        saved = await stored(c, cid)
    eq(shape(events), "start → delta×2 → tool_call → tool_result → delta×2 → tool_call → tool_result → delta → "
                      "usage → done", "イベント列")
    eq((data_of(events, "tool_result")[-1]["output"], data_of(events, "delta")[-1]["text"]),
       (STEP_LIMIT, STEP_LIMIT_NOTE), "最後の tool_result と締めの delta")
    eq(data_of(events, "done"), [{"stop_reason": "max_steps"}], "done")
    eq(rows_of(saved[:6]), [("user", "complete", None), ("assistant", "complete", "tool_use"),
                            ("user", "complete", None), ("assistant", "complete", "tool_use"),
                            ("user", "complete", None), ("assistant", "complete", "max_steps")], "1往復目の保存")
    eq((saved[5]["content"], saved[5]["id"]), (text(STEP_LIMIT_NOTE), events[0]["data"]["message_id"]), "締めの発言")
    sent = next_fake.requests[0].messages
    eq((len(sent), alternates(sent), "stop_reason" in sent[5]), (7, True, False), "次の往復で送った messages")
    return "LLM 呼び出し 2 回で max_steps・締めの assistant（stop_reason=max_steps）を delta でも送る・次の往復は交互のまま"


@dbcheck("V7 開始前の 429・529：JSON のエラー本文で返し、発言は1件も保存しない")
async def _():
    got = {}
    for fault in ("429", "529"):
        async with mock_llm({"x-mock-fault": fault}) as (provider, counter):
            with wired(app, provider, counter=counter):
                async with asgi_client(app) as c:
                    cid = await new_conversation(c)
                    r = await c.post(f"/api/conversations/{cid}/messages", json={"content": PROMPT})
                    saved = await stored(c, cid)
        err = r.json()["error"]
        eq(err["message"], MESSAGES[err["type"]], "固定文")
        got[fault] = (r.status_code, r.headers["content-type"], err["type"], r.headers.get("retry-after"), len(saved))
    eq(got, {"429": (429, "application/json", "rate_limited", "1", 0),
             "529": (503, "application/json", "upstream_unavailable", None, 0)}, "応答と保存")
    return "429 → 429 rate_limited（retry-after: 1）・529 → 503 upstream_unavailable・どちらも保存 0 件"


@dbcheck("V8 途中の上流エラー：送ったところまでを partial で保存してから error を送る（done は送らない）")
async def _():
    results = {}
    async with mock_llm({"x-mock-fault": "sse-error"}) as (provider, counter):
        with wired(app, provider, counter=counter):
            async with asgi_client(app) as c:
                cid = await new_conversation(c)
                _, events = await post_message(c, cid, PROMPT)
                results["sse-error"] = (events, await stored(c, cid))
    for label, second in (("2回目が 529", [TextDelta("作り方は"), ProviderError("overloaded", provider="fake")]),
                          ("2回目が 429", [ProviderError("rate_limited", provider="fake", retry_after=1)])):
        fake = FakeProvider(tool_turn("toolu_p1")[0], second)
        with wired(app, fake):
            async with asgi_client(app) as c:
                cid = await new_conversation(c)
                _, events = await post_message(c, cid, "R001 の作り方は？")
                results[label] = (events, await stored(c, cid))
    events, saved = results["sse-error"]
    eq((shape(events), data_of(events, "error")[0]["type"]), ("start → delta×2 → error", "upstream_error"), "sse-error")
    eq(rows_of(saved), [("user", "complete", None), ("assistant", "partial", None)], "sse-error の保存")
    eq((saved[1]["content"], saved[1]["id"]), (text(fixture_texts()[0][:12]), events[0]["data"]["message_id"]),
       "partial の中身")
    for label, (kind, partial) in {"2回目が 529": ("upstream_unavailable", text("作り方は")),
                                   "2回目が 429": ("rate_limited", [])}.items():
        events, saved = results[label]
        eq(data_of(events, "error")[0]["type"], kind, f"{label}: error の種別")
        eq((rows_of(saved), saved[-1]["content"], pairs_ok(as_messages(saved))),
           ([("user", "complete", None), ("assistant", "complete", "tool_use"), ("user", "complete", None),
             ("assistant", "partial", None)], partial, True), f"{label}: 保存")
    eq(shape(results["2回目が 429"][0]), "start → delta×2 → tool_call → tool_result → error", "2回目が 429 のイベント列")
    return (f"sse-error → start → delta×2 → error（upstream_error）・partial に「{fixture_texts()[0][:12]}」・"
            "2回目の呼び出しで失敗 → 閉じた組は complete・締めの assistant は partial")


@dbcheck("V9 途中切断：tool_result を受け取った直後に切ると、閉じた組と空の partial を保存する")
async def _():
    pausing = PausingProvider(FakeProvider(*tool_turn("toolu_c1")), pause_on=2, seconds=2.0)
    before = len(app.state.outcomes)
    async with asgi_client(app) as c:
        cid = await new_conversation(c)
    with wired(app, pausing):
        async with serve(app, PORT) as url:
            got = await read_until(f"{url}/api/conversations/{cid}/messages", {"content": "R001 の作り方は？"},
                                   stop="tool_result")
            await wait_until(lambda: len(app.state.outcomes) > before, 10.0, "後始末が終わらない")
    outcome = app.state.outcomes[-1]
    async with asgi_client(app) as c:
        saved = await stored(c, cid)
    eq(shape(got), "start → delta×2 → tool_call → tool_result", "受け取ったイベント")
    assert outcome.reason in ("client_disconnected", "cancelled"), outcome.reason
    eq((outcome.saved, outcome.error_type, pausing.calls, pausing.finished), ("partial", None, 2, 1), "結末と上流")
    eq(rows_of(saved), [("user", "complete", None), ("assistant", "complete", "tool_use"), ("user", "complete", None),
                        ("assistant", "partial", None)], "保存した発言")
    eq((saved[-1]["content"], saved[-1]["id"]), ([], outcome.message_id), "partial の中身")
    return "2回目の LLM 呼び出しは最後まで読まれない・保存は user / assistant / user / assistant（partial・空）"


@dbcheck("V10 中断のあとの履歴：partial に注記を足して送り、user は連結せずに間を閉じる（未決事項2）")
async def _():
    use = {"type": "tool_use", "id": "toolu_old", "name": "get_recipe", "input": {"recipe_id": "R001"}}
    result = {"type": "tool_result", "tool_use_id": "toolu_old", "content": "{}", "is_error": False}
    fake = FakeProvider(fake_script("続きをお伝えしますね。"))
    async with asgi_client(app) as c:
        cid = await new_conversation(c)
        async with SessionLocal() as session:  # 途中で切れた往復を直接作る
            await repo.append_messages(session, cid, [
                StoredMessage("user", text("R001 の作り方は？")),
                StoredMessage("assistant", [use], stop_reason="tool_use"),
                StoredMessage("user", [result]),
                StoredMessage("assistant", [], status="partial")])
            await session.commit()
        with wired(app, fake):
            await post_message(c, cid, "さっきの続きを教えて")
    sent = fake.requests[0].messages
    eq([m["role"] for m in sent], ["user", "assistant", "user", "assistant", "user"], "送った messages")
    eq(sent[3]["content"], text(INTERRUPTED_NOTE), "partial の assistant")
    legacy = [Message(role="user", content=text("R001 の作り方は？"), status="complete"),
              Message(role="assistant", content=[use], status="complete"),
              Message(role="user", content=[result], status="complete")]  # tool_result だけの user で終わる旧データ
    fixed = with_new_user(for_model(legacy), "続きは？")
    merged = [*for_model(legacy)[:2], {"role": "user", "content": [result, *text("続きは？")]}]
    eq(([m["role"] for m in fixed], fixed[3]), (["user", "assistant", "user", "assistant", "user"], note_message()),
       "旧データ")
    eq((len(split_groups(fixed)), len(split_groups(merged))), (2, 1), "組の数（分けたまま／連結）")
    return "partial の assistant に注記を足して送る・旧データにも注記を挟む・連結すると split_groups が 2 組を 1 組と見誤る"


@dbcheck("V11 履歴の切り捨て（Session 7）：古い組から落とし、tool_use と tool_result は分断しない")
async def _():
    fake = FakeProvider(fake_script("三日目は親子丼にしましょう。"))
    async with asgi_client(app) as c:
        cid = await new_conversation(c)
        with wired(app, FakeProvider(*tool_turn("toolu_d1"), *tool_turn("toolu_d2"))):
            for q in ("一日目の夕飯は？", "二日目の夕飯は？"):
                await post_message(c, cid, q)
        groups = split_groups(with_new_user(as_messages(await stored(c, cid)), "三日目の夕飯は？"))
        budget = await ApproxTokenCounter().count(flatten(groups[1:]), SYSTEM)  # 最後の2組がちょうど収まる予算
        with wired(app, fake, budget=budget):
            await post_message(c, cid, "三日目の夕飯は？")
        with wired(app, FakeProvider(fake_script("呼ばれないはず")), budget=10):
            too = await c.post(f"/api/conversations/{cid}/messages", json={"content": "三日目の夕飯は？"})
    sent = fake.requests[0].messages
    eq((len(groups), sent), (3, flatten(groups[1:])), "送った履歴")
    eq(([m["role"] for m in sent], pairs_ok(sent)), (["user", "assistant", "user", "assistant", "user"], True),
       "role と組")
    eq((too.status_code, too.json()["error"]["message"]), (422, TOO_LONG_MESSAGE), "最新の組だけで予算を超える")
    return "3 組のうち古い 1 組を落として送る（組は分断しない）・最新の組だけで予算を超えたら 422"


@dbcheck("V12 テスト（pytest）：同じテストを FakeProvider と mockllm の両方に流す")
async def _():
    r = subprocess.run([sys.executable, "-m", "pytest", "src/mid01/test_mid01.py", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout[-3000:]}{r.stderr[-2000:]}")
    m = re.search(r"(\d+) passed", lines[-1] if lines else "")
    assert m, lines[-1:]
    eq(int(m.group(1)), 8, "通ったテストの数")
    return "pytest：8 passed（Fake と mockllm の両方で、正常系・開始前の 429・途中の失敗）"


finish("mid01")
