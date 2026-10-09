"""Session 7（会話履歴の永続化）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session07/verify.py
    docker compose exec api bash verify-all.sh src/session07   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import asyncio
import uuid

from kondate.db import SessionLocal
from kondate.verifykit import eq, finish
from src.session07 import repo
from src.session07.app import HistorySettings, app, get_counter, get_history_settings, get_provider
from src.session07.harness import (PROMPT, alembic, client_for, dbcheck, mock_llm, mock_stats, post_sse,
                                   reset_mock, reset_schema, scalar, seed_messages, seed_turns, shape, upgraded)
from src.session07.history import fit_history, fit_with_summary, split_groups
from src.session07.models import new_id
from src.session07.providers import FakeProvider, Usage, fake_script
from src.session07.tokens import ApproxTokenCounter

TOOL_HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": PROMPT}]},
    {"role": "assistant", "content": [
        {"type": "text", "text": "条件に合うレシピを探しますね。"},
        {"type": "tool_use", "id": "toolu_s07_1", "name": "search_recipes",
         "input": {"ingredients": ["鶏むね肉", "キャベツ"], "max_minutes": 20}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_s07_1", "content": '{"count": 12, "recipes": [{"id": "R001"}]}'}]},
    {"role": "assistant", "content": [{"type": "text", "text": "鶏むね肉とキャベツの塩炒めがおすすめです。"}]},
    {"role": "user", "content": [{"type": "text", "text": "副菜も教えてください。"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "豆腐とわかめのみそ汁はいかがですか。"}]},
    {"role": "user", "content": [{"type": "text", "text": "明日の朝ごはんは何がいいですか。"}]},
]


async def version_and_status() -> tuple[object, bool]:
    version = await scalar("SELECT version_num FROM s07.alembic_version")
    has_status = await scalar("SELECT count(*) FROM information_schema.columns "
                              "WHERE table_schema = 's07' AND table_name = 'messages' AND column_name = 'status'")
    return version, bool(has_status)


@dbcheck("V1 alembic upgrade head でスキーマ s07 にテーブルができる")
async def _():
    await reset_schema()
    log = await asyncio.to_thread(alembic, "upgrade", "head")
    eq(upgraded(log), ["0001", "0002"], "適用されたリビジョン")
    tables = await scalar("SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM information_schema.tables "
                          "WHERE table_schema = 's07'")
    eq(tables, "alembic_version, conversations, messages", "s07 のテーブル")
    eq(await scalar("SELECT version_num FROM s07.alembic_version"), "0002", "現在の版")
    return f"0001 → 0002・テーブル {tables}"


@dbcheck("V2 downgrade -1 で messages.status が消え、upgrade head で戻る")
async def _():
    await asyncio.to_thread(alembic, "downgrade", "-1")
    eq(await version_and_status(), ("0001", False), "downgrade -1 の後（版, status 列の有無）")
    await asyncio.to_thread(alembic, "upgrade", "head")
    eq(await version_and_status(), ("0002", True), "upgrade head の後")
    return "0002 → 0001（status 列なし）→ 0002（status 列あり）"


@dbcheck("V3 alembic check：モデルとマイグレーションに差がない")
async def _():
    out = await asyncio.to_thread(alembic, "check")
    assert "No new upgrade operations detected." in out, out
    return "No new upgrade operations detected."


@dbcheck("V4 会話と発言を保存して読み戻せる（UUIDv7・seq・JSONB）")
async def _():
    async with SessionLocal() as s:
        conv = await repo.create_conversation(s, user_id="u001", title="ツールを使った相談")
        await repo.append_turn(s, conv.id, user_content=TOOL_HISTORY[0]["content"],
                               assistant_content=TOOL_HISTORY[1]["content"])
        await repo.append_turn(s, conv.id, user_content=TOOL_HISTORY[2]["content"],
                               assistant_content=TOOL_HISTORY[3]["content"])
        await s.commit()
    async with SessionLocal() as s:  # 別のセッションで読み直す（キャッシュではなく DB から）
        rows = await repo.load_messages(s, conv.id)
    eq(uuid.UUID(conv.id).version, 7, "会話 ID の UUID バージョン")
    eq({uuid.UUID(r.id).version for r in rows}, {7}, "発言 ID の UUID バージョン")
    eq([r.seq for r in rows], [1, 2, 3, 4], "seq")
    eq(repo.to_api_messages(rows), TOOL_HISTORY[:4], "content のブロック")
    eq({r.status for r in rows}, {"complete"}, "status")
    return "UUID バージョン 7・seq=[1, 2, 3, 4]・tool_use / tool_result のブロックがそのまま戻る"


@dbcheck("V5 履歴を「組」に分け、古い組から丸ごと切り捨てる")
async def _():
    groups = split_groups(TOOL_HISTORY)
    eq([len(g) for g in groups], [4, 2, 1], "組の大きさ")
    fitted = await fit_history(TOOL_HISTORY, ApproxTokenCounter(), budget=100)
    eq((len(fitted.dropped), fitted.messages[0]["content"][0]["text"]), (4, "副菜も教えてください。"),
       "落とした件数と残りの先頭")
    return "組 3 個（4件・2件・1件）・tool_use と tool_result を含む最初の組を丸ごと落とし、残りは user の発言から始まる"


@dbcheck("V6 count_tokens（mockllm）と近似カウンタが同じ値を返す")
async def _():
    approx = ApproxTokenCounter()
    async with mock_llm() as (_, counter):
        got = [await c.count(m) for m in (seed_messages(0), seed_messages(6)) for c in (counter, approx)]
    eq(got, [34, 34, 322, 322], "count_tokens と近似（新しい発言だけ・6往復＋新しい発言）")
    return "新しい発言だけ 34・6往復＋新しい発言 322（count_tokens と近似で一致）"


@dbcheck("V7 予算 200 に収まるよう、DB の履歴から古い往復を切り捨てる")
async def _():
    async with SessionLocal() as s:
        conv = await repo.create_conversation(s, user_id="u001")
        await seed_turns(s, conv.id, 6)
        await s.commit()
        history = repo.to_api_messages(await repo.load_messages(s, conv.id))
    await reset_mock()
    async with mock_llm() as (_, counter):
        fitted = await fit_history([*history, seed_messages(0)[0]], counter, budget=200)
    calls = (await mock_stats())["by_path"].get("/v1/messages/count_tokens")
    eq((len(fitted.dropped), len(fitted.messages), fitted.input_tokens), (6, 7, 178), "落とした件数・残り・トークン")
    eq((fitted.count_calls, calls), (4, 4), "count_tokens の回数（自分で数えた値・mockllm の統計）")
    return "3往復（6件）を落として 7件・178 トークン・count_tokens 4 回"


@dbcheck("V8 落とした分を要約して、残した先頭の発言に添える")
async def _():
    summary = "ユーザーは一日目から四日目の夕飯に鶏むね肉とキャベツの塩炒めを提案された。"
    fake = FakeProvider(fake_script(summary, usage=Usage(200, 37)))
    fitted = await fit_with_summary(seed_messages(6), ApproxTokenCounter(), fake, budget=200, summary_tokens=40)
    first = fitted.messages[0]["content"]
    eq((len(fitted.dropped), len(fitted.messages)), (8, 5), "落とした件数・残り")
    eq(first[0]["text"], f"（ここまでの会話の要約）\n{summary}", "先頭に足した要約")
    eq(first[1]["text"], "五日目の夕飯の献立を考えてください。", "元の発言は残る")
    eq((fitted.input_tokens, fitted.count_calls), (180, 5), "トークンと数えた回数")
    assert fake.requests[0].messages[0]["content"].count("ユーザー: ") == 4, fake.requests[0].messages
    return "4往復（8件）を要約・残り5件・180 トークン（予算 200）・数えた回数 5"


@dbcheck("V9 POST …/messages：ストリーミングの完了後に1往復を保存し、次の発言で履歴を送る")
async def _():
    async with mock_llm() as (provider, counter), client_for(app) as c:
        app.dependency_overrides.update({get_provider: lambda: provider, get_counter: lambda: counter})
        try:
            r = await c.post("/api/conversations", json={"user_id": "u001", "title": "今週の夕飯"})
            eq(r.status_code, 201, f"会話の作成（{r.text}）")
            cid = r.json()["id"]
            status, events = await post_sse(c, f"/api/conversations/{cid}/messages", {"content": PROMPT})
            eq((status, shape(events)), (200, "start → delta×32 → usage → done"), "1回目のイベント")
            eq(events[-2]["data"], {"input_tokens": 34, "output_tokens": 181}, "1回目の usage")
            detail = (await c.get(f"/api/conversations/{cid}")).json()
            msgs = detail["messages"]
            eq([(m["seq"], m["role"], m["status"]) for m in msgs], [(1, "user", "complete"),
                                                                  (2, "assistant", "complete")], "保存された発言")
            eq(msgs[1]["id"], events[0]["data"]["message_id"], "assistant の id と start.message_id")
            eq(len(msgs[1]["content"][0]["text"]), 192, "assistant の本文の文字数")
            status, events = await post_sse(c, f"/api/conversations/{cid}/messages",
                                            {"content": "副菜も教えてください。"})
            eq(events[-2]["data"]["input_tokens"], 232, "2回目の input_tokens（34 + 履歴 184 + 14）")
            eq(len((await c.get(f"/api/conversations/{cid}")).json()["messages"]), 4, "2往復で4件")
        finally:
            app.dependency_overrides.clear()
    return "start → delta×32 → usage → done・保存2件（assistant の id = start.message_id）・2回目の input_tokens=232"


@dbcheck("V10 途中で失敗したとき：discard は何も残さず、partial は途中までを残す")
async def _():
    got = {}
    async with mock_llm(fault="sse-error") as (provider, counter), client_for(app) as c:
        for policy in ("discard", "partial"):
            hs = HistorySettings(history_on_failure=policy)
            app.dependency_overrides.update({
                get_provider: lambda: provider, get_counter: lambda: counter, get_history_settings: lambda: hs})
            try:
                cid = (await c.post("/api/conversations", json={"user_id": "u002"})).json()["id"]
                _, events = await post_sse(c, f"/api/conversations/{cid}/messages", {"content": PROMPT})
                msgs = (await c.get(f"/api/conversations/{cid}")).json()["messages"]
            finally:
                app.dependency_overrides.clear()
            got[policy] = (shape(events), events[-1]["data"]["type"],
                           [(m["role"], m["status"], m["content"][0]["text"][:12]) for m in msgs])
    eq(got["discard"], ("start → delta×2 → error", "upstream_error", []), "discard")
    eq(got["partial"], ("start → delta×2 → error", "upstream_error", [
        ("user", "complete", PROMPT[:12]), ("assistant", "partial", "鶏むね肉とキャベツがある")]), "partial")
    return "start → delta×2 → error（upstream_error）・discard は 0件・partial は2件（「鶏むね肉とキャベツがある」）"


@dbcheck("V11 ストリーム開始前のエラーは共通エラー本文（JSON）で返る")
async def _():
    async with mock_llm() as (provider, counter), client_for(app) as c:
        app.dependency_overrides.update({
            get_provider: lambda: provider, get_counter: lambda: counter,
            get_history_settings: lambda: HistorySettings(history_max_input_tokens=20)})
        try:
            r404 = await c.post(f"/api/conversations/{new_id()}/messages", json={"content": PROMPT})
            cid = (await c.post("/api/conversations", json={"user_id": "u003"})).json()["id"]
            r422 = await c.post(f"/api/conversations/{cid}/messages", json={"content": PROMPT})
        finally:
            app.dependency_overrides.clear()
    got = [(r.status_code, r.headers["content-type"], r.json()["error"]["type"]) for r in (r404, r422)]
    eq(got, [(404, "application/json", "not_found"), (422, "application/json", "invalid_request")], "エラー")
    eq(r422.json()["error"]["request_id"], r422.headers["x-request-id"], "request_id")
    return "存在しない会話 → 404 not_found・予算 20 に 34 トークンの発言 → 422 invalid_request"


finish("session07")
