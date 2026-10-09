"""最終プロジェクト（こんだてAI バックエンド）の検証。api コンテナの中で実行する：

    docker compose restart worker          # tasks.py（final.plan_week）を worker に読み込ませる。変更したら毎回
    docker compose exec api python src/final/verify.py

上流は FakeProvider と mockllm の両方を使う（課金なし）。DB はスキーマ final、Redis は final: だけを初期化する。
ジョブの検査（V2・V11）だけは worker が要る。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date
from decimal import Decimal

from kondate.clock import FixedClock
from kondate.db import engine
from kondate.verifykit import check, eq, finish
from kondate.worker import app as celery_app

from src.final.budget import BudgetSettings
from src.final.contract import first, of_type, rebuild, shape
from src.final.errors import MESSAGES
from src.final.harness import (APP, FIXTURE_CALLS, PROMPT, alembic, assert_error, bearer, clear_redis, client_for,
                               conversation,
                               dbcheck, fake_routes, fake_text, fake_tool_search, fresh, issue, mock_routes,
                               mock_stats, post_chat, prepare_db, reset_mock, rows, scalar, ui, user_message, wait_job)
from src.final.limiter import LimitSettings
from src.final.loop import ToolLimits
from src.final.planner import build_plan, find_user
from src.final.providers import FakeProvider, ProviderError, TextDelta, ToolCall, Usage, fake_script
from src.final.turn import STEP_LIMIT_NOTE
from src.final.uimessages import UIMessageIn, to_anthropic_messages

CLOCK = FixedClock()  # 2026-10-02 18:00 JST
JOB_ID = re.compile(r"job_[0-9A-HJKMNP-TV-Z]{26}")
TOOL_STEP = ["start-step", "text-start", "text-delta", "text-end", "tool-input-start", "tool-input-delta",
             "tool-input-available", "tool-output-available", "finish-step"]
TEXT_STEP = ["start-step", "text-start", "text-delta", "text-end", "finish-step"]
TOOL_TURN = " > ".join(["start", *TOOL_STEP, *TOOL_STEP, *TEXT_STEP, "data-usage", "finish"])
TOOL_PARTS = ["step-start", "text(done)", "tool-search_recipes(output-available)",
              "step-start", "text(done)", "tool-get_recipe(output-available)",
              "step-start", "text(done)", "data-usage"]
HEADERS = {"content-type": "text/event-stream", "cache-control": "no-cache", "connection": "keep-alive",
           "x-vercel-ai-ui-message-stream": "v1", "x-accel-buffering": "no"}


async def _setup() -> dict[str, str]:
    await prepare_db()
    keys = {u: await issue(u, CLOCK) for u in ("u001", "u002", "u003")}
    await engine.dispose()
    return keys


KEYS = asyncio.run(_setup())


def is_uuid7(value: str) -> bool:
    return uuid.UUID(value).version == 7


@dbcheck("V1 Alembic：スキーマ final に5つの表と版の表（0001）を作る")
async def _():
    tables = [r[0] for r in await rows("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_schema = 'final' ORDER BY table_name")]
    eq(tables, ["alembic_version", "api_keys", "conversations", "messages", "usage_events", "users"], "表")
    eq(await scalar("SELECT version_num FROM final.alembic_version"), "0001", "版")
    eq("0001" in alembic("current"), True, "alembic current")
    return "alembic_version・api_keys・conversations・messages・usage_events・users（版 0001・版の表も final）"


@check("V2 worker が final.plan_week を読み込んでいる（acks_late・reject_on_worker_lost）")
def _():
    replies = celery_app.control.inspect(timeout=3, limit=1).registered() or {}
    names = {n.split()[0] for tasks in replies.values() for n in tasks}
    assert "final.plan_week" in names, "worker が final.plan_week を知りません。docker compose restart worker を実行してください"
    from src.final.tasks import plan_week
    eq((plan_week.acks_late, plan_week.reject_on_worker_lost, plan_week.ignore_result), (True, True, True), "設定")
    return "final.plan_week（acks_late=True・reject_on_worker_lost=True・ignore_result=True）"


@dbcheck("V3 /health・/ready・CORS・再接続の 204・停止中（drain）の 503")
async def _():
    await fresh()
    async with client_for(fake_routes(fake_text()), clock=CLOCK) as c:
        health = await c.get("/health")
        ready = await c.get("/ready")
        pre = await c.options("/api/chat", headers={
            "Origin": "http://localhost:3710", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        resume = await c.get("/api/chat/chat-1/stream")
        APP.state.drain.begin()
        draining = await c.get("/ready")
        rejected = await post_chat(c, KEYS["u001"], "chat-drain", [user_message("こんにちは", "m1")])
        health2 = await c.get("/health")
    eq((health.status_code, health.json()), (200, {"status": "ok"}), "/health")
    eq((ready.status_code, ready.json()),
       (200, {"status": "ready", "checks": {"postgres": "ok", "redis": "ok", "mockllm": "ok"}}), "/ready")
    eq((pre.status_code, pre.headers.get("access-control-allow-origin")), (200, "http://localhost:3710"), "CORS")
    eq((resume.status_code, resume.content), (204, b""), "GET /api/chat/{id}/stream")
    eq((draining.status_code, draining.json()["status"]), (503, "draining"), "drain 中の /ready")
    assert_error(rejected, 503, "service_unavailable", MESSAGES["service_unavailable"])
    eq((rejected.headers["retry-after"], health2.status_code), ("1", 200), "retry-after と drain 中の /health")
    eq(await scalar("SELECT count(*) FROM final.conversations"), 0, "保存しない")
    return ("/health 200・/ready 200（postgres・redis・mockllm が ok）・CORS は localhost:3710 を許可・"
            "GET /api/chat/{id}/stream は 204・drain 中は /ready 503 と POST 503 service_unavailable（retry-after: 1）")


@dbcheck("V4 契約（FakeProvider）：ヘッダ5個・data 行・[DONE]・§3.4 の並び＋data-usage・messageMetadata")
async def _():
    await fresh()
    async with client_for(fake_routes(fake_tool_search()), clock=CLOCK) as c:
        r = await post_chat(c, KEYS["u001"], "chat-fake", [user_message(PROMPT, "m1")])
        chunks = ui(r)
        saved = await conversation(c, KEYS["u001"], "chat-fake")
    start, fin, usage = first(chunks, "start"), first(chunks, "finish"), first(chunks, "data-usage")
    eq({k: r.headers[k] for k in HEADERS}, HEADERS, "ヘッダ5個")
    eq(shape(chunks), TOOL_TURN, "チャンクの並び")
    eq(rebuild(chunks), TOOL_PARTS, "復元した parts")
    eq([c["toolName"] for c in of_type(chunks, "tool-input-available")], ["search_recipes", "get_recipe"], "ツール")
    eq(usage, {"type": "data-usage", "id": "usage", "data": {
        "input_tokens": 600, "output_tokens": 60, "cache_read_input_tokens": 0, "plan": "free",
        "used_today": 660, "limit_today": 20000}}, "data-usage")
    eq((fin["finishReason"], sorted(fin["messageMetadata"])), ("stop", ["conversation_id", "request_id", "usage"]),
       "finish")
    eq((fin["messageMetadata"]["conversation_id"], fin["messageMetadata"]["request_id"]),
       ("chat-fake", r.headers["x-request-id"]), "messageMetadata")
    eq(is_uuid7(start["messageId"]), True, "start.messageId は UUIDv7")
    eq(([m["role"] for m in saved], saved[-1]["id"]), (["user", "assistant"], start["messageId"]),
       "GET の UIMessage[]")
    eq([p["type"] for p in saved[-1]["parts"]],
       ["step-start", "text", "tool-search_recipes", "step-start", "text", "tool-get_recipe", "step-start", "text"],
       "GET の parts")
    eq((r.headers["x-ratelimit-limit-requests"], r.headers["x-ratelimit-remaining-requests"],
        r.headers["x-ratelimit-limit-tokens"]), ("10", "9", "20000"), "x-ratelimit-*")
    ledger = await rows("SELECT turn_id, request_id, usage_source, outcome, input_tokens, output_tokens, "
                        "cost_usd FROM final.usage_events")
    eq(ledger, [(start["messageId"], r.headers["x-request-id"], "upstream", "completed", 600, 60,
                 Decimal("0.00180000"))], "台帳")
    return ("ヘッダ5個・data 行のみ・[DONE]・start → 3ステップ（ツール2往復）→ data-usage → finish・"
            "data-usage 600/60・used_today 660・finishReason stop・messageId（UUIDv7）が保存した assistant の ID・"
            "台帳 1行（turn_id＝messageId・0.00180000 USD）")


@dbcheck("V5 契約（mockllm・kondate_tool_search）：同じ並びと parts。usage は mockllm の数えた値の合計")
async def _():
    await fresh()
    await reset_mock()
    async with mock_routes() as routes, client_for(routes, clock=CLOCK) as c:
        r = await post_chat(c, KEYS["u001"], "chat-mock", [user_message(PROMPT, "m1")])
        chunks = ui(r)
    stats = (await mock_stats())["requests"]
    usage = first(chunks, "data-usage")["data"]
    outputs = [c["output"] for c in of_type(chunks, "tool-output-available")]
    eq(shape(chunks), TOOL_TURN, "チャンクの並び")
    eq(rebuild(chunks), TOOL_PARTS, "復元した parts")
    eq([(s["scenario"], s["step"]) for s in stats], [("kondate_tool_search", n) for n in (0, 1, 2)], "mockllm")
    eq((usage["input_tokens"], usage["output_tokens"]),
       (sum(s["input_tokens"] for s in stats), sum(s["output_tokens"] for s in stats)), "usage の合計")
    eq(usage["used_today"], usage["input_tokens"] + usage["output_tokens"], "used_today（台帳）")
    eq([x["id"] for x in outputs[0]["recipes"]], ["R001", "R067", "R083", "R112", "R009"], "search_recipes")
    eq(outputs[1]["id"], "R001", "get_recipe")
    eq(first(chunks, "finish")["finishReason"], "stop", "finishReason")
    return ("並びと parts は Fake と同じ・mockllm のステップ 0 → 1 → 2・data-usage は3回の usage の合計・"
            "search_recipes は R001・R067・R083・R112・R009")


@dbcheck("V6 2往復目：GET の UIMessage[] に発言を足して送ると、to_anthropic_messages が保存した履歴に戻す")
async def _():
    await fresh()
    await reset_mock()
    async with mock_routes() as routes, client_for(routes, clock=CLOCK) as c:
        ui(await post_chat(c, KEYS["u001"], "chat-2", [user_message(PROMPT, "m1")]))
        history = await conversation(c, KEYS["u001"], "chat-2")
        second = user_message("ほかに作れるレシピも探して", "m2")
        r = await post_chat(c, KEYS["u001"], "chat-2", [*history, second])
        chunks = ui(r)
        after = await conversation(c, KEYS["u001"], "chat-2")
    stored = await rows("SELECT m.role, m.content FROM final.messages m JOIN final.conversations c "
                        "ON c.id = m.conversation_id WHERE c.chat_id = 'chat-2' ORDER BY m.seq")
    converted = to_anthropic_messages([UIMessageIn(**m) for m in history] + [UIMessageIn(**second)])
    eq(converted[:6], [{"role": role, "content": content} for role, content in stored[:6]], "往復の変換")
    stats = (await mock_stats())["requests"]
    eq([s["step"] for s in stats], [0, 1, 2, 0, 1, 2], "mockllm のステップ")
    eq(stats[3]["input_tokens"] > stats[0]["input_tokens"], True, "2往復目は履歴の分だけ入力が大きい")
    eq((shape(chunks), [m["role"] for m in after], len(stored)),
       (TOOL_TURN, ["user", "assistant", "user", "assistant"], 12), "2往復目")
    return ("1往復目の UIMessage[]（step-start 区切り・ツール part）を Anthropic の6件に戻せる・"
            "mockllm のステップ [0,1,2,0,1,2]・保存は12件・GET は user/assistant ×2")


@dbcheck("V7 再生成（regenerate-message）：捨てられた応答を会話の記録から外して、新しい応答に置き換える")
async def _():
    await fresh()
    async with client_for(fake_routes(FakeProvider(fake_script("一つ目の答え", usage=Usage(10, 5)),
                                                    fake_script("二つ目の答え", usage=Usage(20, 5)),
                                                    fake_script("作り直した答え", usage=Usage(20, 5)))),
                          clock=CLOCK) as c:
        u1, u2 = user_message("今夜の献立は？", "m1"), user_message("副菜も教えて", "m2")
        first_id = first(ui(await post_chat(c, KEYS["u001"], "chat-re", [u1])), "start")["messageId"]
        history = await conversation(c, KEYS["u001"], "chat-re")
        old_id = first(ui(await post_chat(c, KEYS["u001"], "chat-re", [*history, u2])), "start")["messageId"]
        new = ui(await post_chat(c, KEYS["u001"], "chat-re", [*history, u2], trigger="regenerate-message",
                                 message_id=old_id))
        after = await conversation(c, KEYS["u001"], "chat-re")
    new_id = first(new, "start")["messageId"]
    texts = [p["text"] for m in after for p in m["parts"] if p["type"] == "text"]
    eq([m["id"] for m in after if m["role"] == "assistant"], [first_id, new_id], "assistant の ID")
    eq(texts, ["今夜の献立は？", "一つ目の答え", "副菜も教えて", "作り直した答え"], "会話の記録")
    eq(old_id in [m["id"] for m in after], False, "古い応答は残らない")
    return "再生成のあと GET は4件（一つ目の答え・作り直した答え）・捨てた応答の ID は残らない"


@dbcheck("V8 開始前のエラーは JSON（401・422・429・402・503）。どれも会話にも台帳にも何も残さない")
async def _():
    await fresh()
    msg = [user_message("今夜の献立は？", "m1")]
    async with client_for(fake_routes(fake_text()), clock=CLOCK,
                          limits=LimitSettings(free_requests_per_minute=1)) as c:
        no_key = await c.post("/api/chat", json={"id": "chat-e", "messages": msg, "trigger": "submit-message"})
        empty = await post_chat(c, KEYS["u001"], "chat-e", [])
        last_ai = await post_chat(c, KEYS["u001"], "chat-e", [*msg, {"id": "a1", "role": "assistant", "parts": [
            {"type": "text", "text": "はい"}]}])
        ok = await post_chat(c, KEYS["u001"], "chat-ok", msg)
        limited = await post_chat(c, KEYS["u001"], "chat-e", msg)
    # 時計を止めているので、空になったトークンバケットは補充されない。次の検査の前に Redis の状態を消す
    await clear_redis()
    async with client_for(fake_routes(fake_text()), clock=CLOCK,
                          limits=LimitSettings(free_tokens_per_day=100)) as c:
        quota = await post_chat(c, KEYS["u001"], "chat-e", msg)
    async with client_for(fake_routes(fake_text()), clock=CLOCK,
                          budget=BudgetSettings(users={"u003": Decimal("0.001")})) as c:
        budget = await post_chat(c, KEYS["u003"], "chat-e", msg)
    await reset_mock()
    async with mock_routes() as routes, client_for(routes, clock=CLOCK) as c:
        upstream = await post_chat(c, KEYS["u002"], "chat-e", msg, headers={"x-mock-fault": "529"})
    calls = (await mock_stats())["total"]
    err = assert_error(no_key, 401, "unauthorized", "認証が必要です")
    eq(no_key.headers.get("www-authenticate"), "Bearer", "WWW-Authenticate")
    assert_error(empty, 422, "invalid_request")
    assert_error(last_ai, 422, "invalid_request", "最後の発言は user のテキストにしてください。")
    ui(ok)
    assert_error(limited, 429, "rate_limited", MESSAGES["rate_limited"])
    eq((limited.headers["x-ratelimit-limit-requests"], limited.headers["x-ratelimit-remaining-requests"],
        "retry-after" in limited.headers), ("1", "0", True), "rate_limited のヘッダ")
    assert_error(quota, 429, "quota_exceeded", MESSAGES["quota_exceeded"])
    eq((quota.headers["retry-after"], quota.headers["x-ratelimit-limit-tokens"]), ("21600", "100"),
       "quota_exceeded のヘッダ（18:00 → 翌 0:00 は 21600 秒）")
    assert_error(budget, 402, "budget_exceeded", MESSAGES["budget_exceeded"])
    eq("retry-after" in budget.headers, False, "402 に retry-after は付けない")
    assert_error(upstream, 503, "upstream_unavailable", MESSAGES["upstream_unavailable"])
    eq((calls, "overloaded" in upstream.text, "mockllm" in upstream.text), (4, False, False),
       "529：primary 2回＋light 2回で諦める・上流の文は出さない")
    eq((await rows("SELECT chat_id FROM final.conversations"),
        await scalar("SELECT count(*) FROM final.usage_events")), ([("chat-ok",)], 1), "残ったのは成功した1往復だけ")
    eq(err["request_id"].startswith("req_"), True, "request_id")
    return ("401 unauthorized（WWW-Authenticate: Bearer）・422 invalid_request×2・429 rate_limited（x-ratelimit-*）・"
            "429 quota_exceeded（retry-after 21600）・402 budget_exceeded・503 upstream_unavailable（上流4回）・"
            "失敗した要求は会話にも台帳にも残らない")


@dbcheck("V9 途中のエラー：error {errorText: 固定文} → finish(error) → [DONE]。送ったところまでを partial で保存")
async def _():
    await fresh()
    failing = FakeProvider([TextDelta("条件に合う"), TextDelta("レシピを"),
                            ProviderError("overloaded", provider="fake", status_code=529)])
    async with client_for(fake_routes(failing), clock=CLOCK) as c:
        fake = ui(await post_chat(c, KEYS["u001"], "chat-mid", [user_message("今夜の献立は？", "m1")]))
        saved = await conversation(c, KEYS["u001"], "chat-mid")
    await reset_mock()
    async with mock_routes() as routes, client_for(routes, clock=CLOCK) as c:
        r = await post_chat(c, KEYS["u002"], "chat-sse", [user_message(PROMPT, "m1")],
                            headers={"x-mock-fault": "sse-error"})
        mock = ui(r)
    eq(shape(fake), "start > start-step > text-start > text-delta > error > finish", "Fake の並び")
    eq((first(fake, "error")["errorText"], first(fake, "finish")),
       (MESSAGES["upstream_unavailable"], {"type": "finish", "finishReason": "error"}), "Fake の error と finish")
    eq([(m["role"], m["id"]) for m in saved], [("user", saved[0]["id"]), ("assistant", first(fake, "start")["messageId"])],
       "保存（user と assistant）")
    eq(saved[1]["parts"], [{"type": "step-start"}, {"type": "text", "text": "条件に合うレシピを", "state": "done"}],
       "partial の中身")
    for chat_id in ("chat-mid", "chat-sse"):  # 2つの会話それぞれが user（complete）＋assistant（partial）で閉じる
        eq(await rows("SELECT m.status FROM final.messages m JOIN final.conversations c ON c.id = m.conversation_id "
                      "WHERE c.chat_id = :cid ORDER BY m.seq", cid=chat_id), [("complete",), ("partial",)],
           f"status（{chat_id}）")
    eq(await rows("SELECT usage_source, outcome FROM final.usage_events ORDER BY created_at"),
       [("estimated", "failed"), ("estimated", "failed")], "台帳（見積もり）")
    eq((first(mock, "error")["errorText"], first(mock, "finish")["finishReason"]),
       (MESSAGES["upstream_error"], "error"), "mockllm sse-error")
    eq(("overloaded_error" in r.text, "mockllm" in r.text, "data-usage" in r.text), (False, False, False),
       "上流の生の文を出さない・usage は送らない")
    return ("Fake 529 → error（upstream_unavailable の固定文）→ finish(error) → [DONE]・partial に送った文を保存・"
            "mockllm sse-error → upstream_error の固定文・上流の文は本文に出ない・台帳は estimated/failed")


@dbcheck("V10 ツールの失敗は tool-output-error（finish-step の前）。ステップ上限は締めの文と finishReason other")
async def _():
    await fresh()
    broken = FakeProvider(
        fake_script("確認します。", tool_calls=[ToolCall("toolu_x", "get_recipe", {"recipe_id": "R999"})]),
        fake_script("そのレシピは見つかりませんでした。"))
    looping = FakeProvider(fake_script("調べます。", tool_calls=[ToolCall("toolu_y", "get_recipe",
                                                                            {"recipe_id": "R001"})]))
    async with client_for(fake_routes(broken), clock=CLOCK) as c:
        bad = ui(await post_chat(c, KEYS["u001"], "chat-tool", [user_message("R999 の作り方は？", "m1")]))
    async with client_for(fake_routes(looping), clock=CLOCK, tool_limits=ToolLimits(max_steps=2)) as c:
        capped = ui(await post_chat(c, KEYS["u001"], "chat-cap", [user_message("R001 の作り方は？", "m1")]))
        saved = await conversation(c, KEYS["u001"], "chat-cap")
    eq(shape(bad), " > ".join(["start", *TOOL_STEP[:7], "tool-output-error", "finish-step", *TEXT_STEP,
                               "data-usage", "finish"]), "ツール失敗の並び")
    eq(first(bad, "tool-output-error")["errorText"],
       "レシピ R999 はありません。search_recipes の結果にある id を指定してください。", "errorText")
    eq(shape(capped), " > ".join(["start", *TOOL_STEP, *TOOL_STEP[:7], "tool-output-error", "finish-step",
                                  *TEXT_STEP, "data-usage", "finish"]), "ステップ上限の並び")
    eq((of_type(capped, "text-delta")[-1]["delta"], first(capped, "finish")["finishReason"]),
       (STEP_LIMIT_NOTE, "other"), "締めの文と finishReason")
    eq(await rows("SELECT m.role, m.stop_reason FROM final.messages m JOIN final.conversations c "
                  "ON c.id = m.conversation_id WHERE c.chat_id = 'chat-cap' ORDER BY m.seq"),
       [("user", None), ("assistant", "tool_use"), ("user", None), ("assistant", "tool_use"), ("user", None),
        ("assistant", "max_steps")], "保存（往復は assistant で閉じる）")
    eq(saved[-1]["parts"][-1], {"type": "text", "text": STEP_LIMIT_NOTE, "state": "done"}, "GET の最後")
    return ("R999 → tool-output-error（finish-step の前）→ LLM が続けて stop・max_steps=2 → 2回目は実行せず error → "
            "締めの文のステップ → finishReason other・保存の最後は stop_reason=max_steps の assistant")


@dbcheck("V11 plan_week：ツールはジョブを積んで {job_id, status: queued} を返し、ジョブの API で進捗と結果を読める")
async def _():
    await fresh()
    planner = FakeProvider(
        fake_script("1週間の献立づくりを始めます。", tool_calls=[ToolCall("toolu_p", "plan_week", {"days": 3})]),
        fake_script("ジョブを始めました。進み具合は画面に表示されます。"))
    async with client_for(fake_routes(planner), clock=CLOCK) as c:
        chunks = ui(await post_chat(c, KEYS["u002"], "chat-plan", [user_message("3日分の献立を作って", "m1")]))
        output = first(chunks, "tool-output-available")["output"]
        job_id = output["job_id"]
        job = await wait_job(c, job_id, KEYS["u002"])
        events = await c.get(f"/api/jobs/{job_id}/events", headers=bearer(KEYS["u002"]))
        others = [await c.get(f"/api/jobs/{job_id}", headers=bearer(KEYS["u001"])),
                  await c.delete(f"/api/jobs/{job_id}", headers=bearer(KEYS["u001"]))]
        direct = await c.post("/api/jobs/plan-week", json={"days": 2}, headers=bearer(KEYS["u002"]))
        job2 = await wait_job(c, direct.json()["job_id"], KEYS["u002"])
        deleted = await c.delete(f"/api/jobs/{job2['job_id']}", headers=bearer(KEYS["u002"]))
    assert JOB_ID.fullmatch(job_id), job_id
    eq(output, {"job_id": job_id, "status": "queued"}, "ツールの結果")
    eq((job["status"], job["done"], job["total"]), ("succeeded", 3, 3), "ジョブ")
    eq(job["result"], build_plan(find_user("u002"), 3, date(2026, 10, 3)), "結果（2026-10-03 から3日・えび/かに除外）")
    names = [line[len("event: "):] for line in events.text.splitlines() if line.startswith("event: ")]
    eq(names, ["progress"] * 4 + ["done"], "進捗の SSE")
    eq([x.status_code for x in others], [404, 404], "他人のジョブ")
    eq((direct.status_code, direct.json()["status"], direct.headers["location"]),
       (202, "queued", f"/api/jobs/{job2['job_id']}"), "POST /api/jobs/plan-week")
    eq((job2["status"], deleted.status_code, deleted.json()["status"]), ("succeeded", 200, "succeeded"),
       "終わったジョブの DELETE")
    return ("チャットの plan_week → {job_id, status: queued}・worker が3日分を作る（build_plan と一致）・"
            "SSE は progress×4 → done・他人は 404・POST は 202＋Location・終わったジョブの DELETE は 200")


@dbcheck("V12 持ち主の分離と /api/usage：他人の会話は 404、同じ chatId でも利用者ごとに別の会話")
async def _():
    await fresh()
    async with client_for(fake_routes(fake_text()), clock=CLOCK) as c:
        ui(await post_chat(c, KEYS["u001"], "chat-own", [user_message("今夜の献立は？", "m1")]))
        stolen = await c.get("/api/conversations/chat-own", headers=bearer(KEYS["u002"]))
        ui(await post_chat(c, KEYS["u002"], "chat-own", [user_message("お弁当のおかずは？", "m1")]))
        mine = (await c.get("/api/conversations", headers=bearer(KEYS["u001"]))).json()
        theirs = await conversation(c, KEYS["u002"], "chat-own")
        own = await conversation(c, KEYS["u001"], "chat-own")
        usage = (await c.get("/api/usage", headers=bearer(KEYS["u001"]))).json()
        bad_id = await c.get("/api/conversations/bad%20id", headers=bearer(KEYS["u001"]))
    assert_error(stolen, 404, "not_found")
    eq(([m["id"] for m in mine], mine[0]["title"]), (["chat-own"], "今夜の献立は？"), "u001 の一覧")
    eq((own[0]["parts"][0]["text"], theirs[0]["parts"][0]["text"]), ("今夜の献立は？", "お弁当のおかずは？"),
       "同じ chatId でも別の会話")
    eq(usage, {"plan": "free", "used_today": 54, "limit_today": 20000, "requests_per_minute": 10}, "/api/usage")
    eq(bad_id.status_code, 422, "chatId の形式")
    return ("他人の会話は 404 not_found・同じ chatId を別の利用者が使っても混ざらない・"
            "/api/usage は {plan: free, used_today: 54, limit_today: 20000, requests_per_minute: 10}")


@dbcheck("V13 決定事項1：受け取った x-request-id は相関用。同じ ID が2回来ても台帳は turn_id で2行")
async def _():
    await fresh()
    rid = "req_01K6H2J0000000000000000000"
    async with client_for(fake_routes(fake_text()), clock=CLOCK) as c:
        r1 = await post_chat(c, KEYS["u001"], "chat-rid", [user_message("今夜の献立は？", "m1")],
                             headers={"x-request-id": rid})
        r2 = await post_chat(c, KEYS["u001"], "chat-rid2", [user_message("明日の献立は？", "m1")],
                             headers={"x-request-id": rid})
        r3 = await post_chat(c, KEYS["u001"], "chat-rid3", [user_message("副菜は？", "m1")],
                             headers={"x-request-id": "abc"})
    ids = [first(ui(r), "start")["messageId"] for r in (r1, r2)]
    ledger = await rows("SELECT request_id, turn_id FROM final.usage_events WHERE request_id = :rid "
                        "ORDER BY created_at", rid=rid)
    eq((r1.headers["x-request-id"], r2.headers["x-request-id"]), (rid, rid), "受け取った ID をそのまま返す")
    eq(first(ui(r1), "finish")["messageMetadata"]["request_id"], rid, "messageMetadata")
    eq(sorted(ledger), sorted([(rid, ids[0]), (rid, ids[1])]), "台帳は2行（一意キーは turn_id）")
    eq((r3.headers["x-request-id"] != "abc", r3.headers["x-request-id"].startswith("req_")), (True, True),
       "形式に合わない ID は採番し直す")
    return "同じ x-request-id の2往復 → 応答も messageMetadata も同じ ID・台帳は turn_id ごとに2行・形式違いは採番し直す"


finish("final")
