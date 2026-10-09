"""Session 7 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session07
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from kondate.db import SessionLocal
from kondate.verifykit import check, eq, finish
from src.session07 import repo
from src.session07.harness import alembic, client_for, dbcheck, mock_llm, reset_schema, seed_messages
from src.session07.history import fit_history
from src.session07.models import Conversation
from src.session07.q1_list import list_conversations
from src.session07.q2_jsonb import count_tool_messages, tool_names
from src.session07.q3_scope import app as q3_app
from src.session07.q4_drift import pending_changes, with_extra_column
from src.session07.q5_orphans import drop_orphan_tools
from src.session07.q6_partial import INTERRUPTED_NOTE, history_for_model
from src.session07.q6_save_check import run_turn
from src.session07.providers import ProviderError, TextDelta, Usage, fake_script
from src.session07.q7_fast_fit import fit_history_fast, fit_history_linear


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def use(i: str) -> dict:
    return {"type": "tool_use", "id": i, "name": "search_recipes", "input": {"ingredients": ["卵"]}}


def result(i: str) -> dict:
    return {"type": "tool_result", "tool_use_id": i, "content": '{"count": 3}'}


@dbcheck("P1 会話一覧：自分の会話だけを、更新の新しい順に返す")
async def _():
    await reset_schema()
    await asyncio.to_thread(alembic, "upgrade", "head")
    ids = {}
    for title, user in (("一日目", "u001"), ("二日目", "u001"), ("三日目", "u001"), ("別の人", "u002")):
        async with SessionLocal() as s:
            ids[title] = (await repo.create_conversation(s, user_id=user, title=title)).id
            await s.commit()
    async with SessionLocal() as s:  # 一日目に発言が足されて、いちばん新しくなる
        await repo.append_turn(s, ids["一日目"], user_content="続きです", assistant_content=[text("はい。")])
        await s.commit()
    async with SessionLocal() as s:
        titles = [c.title for c in await list_conversations(s, "u001")]
        top = [c.title for c in await list_conversations(s, "u001", limit=1)]
    eq(titles, ["一日目", "三日目", "二日目"], "u001 の一覧")
    eq(top, ["一日目"], "limit=1")
    return "一日目 → 三日目 → 二日目（u002 の会話は出ない）・limit=1 で一日目だけ"


@dbcheck("P2 JSONB の @> で tool_use を含む発言を数える")
async def _():
    async with SessionLocal() as s:
        conv = await repo.create_conversation(s, user_id="u001")
        await repo.append_turn(s, conv.id, user_content="卵で何か作れる？", assistant_content=[text("探します。"), use("t1")])
        await repo.append_turn(s, conv.id, user_content=[result("t1")], assistant_content=[text("卵焼きはどうですか。")])
        await s.commit()
        got = (await count_tool_messages(s, conv.id), await tool_names(s, conv.id))
    eq(got, (1, ["search_recipes"]), "数と名前")
    return "4件のうち tool_use を含むのは1件（search_recipes）"


@dbcheck("P3 1リクエスト1セッション：失敗したリクエストは何も残さず、同時に送っても混ざらない")
async def _():
    async def count() -> int:
        async with SessionLocal() as s:
            return await s.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == "u005"))

    async with client_for(q3_app) as c:
        before = await count()
        ok = await c.post("/q3/turns", json={"user_id": "u005"})
        ng = await c.post("/q3/turns", json={"user_id": "u005", "fail": True})
        many = await asyncio.gather(*(c.post("/q3/turns", json={"user_id": "u005"}) for _ in range(5)))
    eq((ok.status_code, ng.status_code, ng.json()["error"]["type"]), (201, 500, "internal_error"), "応答")
    eq([r.status_code for r in many], [201] * 5, "同時に5件")
    eq(await count() - before, 6, "増えた会話の数（成功 1 + 同時 5。失敗の分は 0）")
    return "成功 201・失敗 500 internal_error（会話は残らない）・同時に5件 → すべて 201・増えたのは6件"


@dbcheck("P4 マイグレーションの書き忘れを検出する")
async def _():
    eq(await pending_changes(), [], "いまのモデル")
    eq(await pending_changes(with_extra_column()), ["add_column s07.messages.stop_reason"], "列を足したモデル")
    return "いまのモデル → 差なし・stop_reason を足したモデル → add_column s07.messages.stop_reason"


@check("P5 対になっていない tool_use / tool_result を取り除く")
def _():
    cases = [
        ([{"role": "user", "content": "卵で何か作れる？"}, {"role": "assistant", "content": [text("探します。"), use("t1")]}],
         [{"role": "user", "content": [text("卵で何か作れる？")]}, {"role": "assistant", "content": [text("探します。")]}]),
        ([{"role": "user", "content": [text("卵で")]}, {"role": "assistant", "content": [use("t1")]},
          {"role": "user", "content": [text("やっぱり豆腐で")]}],
         [{"role": "user", "content": [text("卵で"), text("やっぱり豆腐で")]}]),
        ([{"role": "user", "content": [result("t9")]}, {"role": "assistant", "content": [text("卵焼きです。")]},
          {"role": "user", "content": [text("副菜は？")]}],
         [{"role": "user", "content": [text("副菜は？")]}]),
        ([{"role": "user", "content": [text("卵で")]}, {"role": "assistant", "content": [use("t1")]},
          {"role": "user", "content": [result("t1")]}, {"role": "assistant", "content": [text("卵焼きです。")]}], None),
    ]
    for i, (given, expected) in enumerate(cases, 1):
        eq(drop_orphan_tools(given), given if expected is None else expected, f"ケース{i}")
    return f"{len(cases)} ケース（末尾の tool_use・結果のない呼び出し・先頭の tool_result・正しい組）"


@check("P6 partial の応答を、書き添えて送る／往復ごと送らない")
def _():
    rows = [{"role": "user", "content": [text("一日目の献立は？")], "status": "complete"},
            {"role": "assistant", "content": [text("塩炒めです。")], "status": "complete"},
            {"role": "user", "content": [text("二日目は？")], "status": "complete"},
            {"role": "assistant", "content": [text("鶏むね肉とキャベツがある")], "status": "partial"}]
    annotated = history_for_model(rows, "annotate")
    dropped = history_for_model(rows, "drop_turn")
    eq((len(annotated), annotated[-1]["content"][-1]["text"]), (4, INTERRUPTED_NOTE), "annotate")
    eq([m["content"][0]["text"] for m in dropped], ["一日目の献立は？", "塩炒めです。"], "drop_turn")
    return "annotate → 4件（末尾に「（この応答は途中で中断されました）」）・drop_turn → 2件"


@dbcheck("P6-2 保存を確かめてから done を送る／途中で失敗したときに残るもの（discard・partial）")
async def _():
    done = fake_script("鶏むね肉とキャベツの塩炒めにしましょう。", usage=Usage(30, 20), stop_reason="end_turn")
    broken = [TextDelta("鶏むね肉と"), TextDelta("キャベツの"), ProviderError("overloaded", provider="fake")]
    eq(await run_turn("discard", done), (["start", *["delta"] * 4, "usage", "done"], None, 2), "保存できた")
    eq(await run_turn("discard", done, save_ok=False),
       (["start", *["delta"] * 4, "error"], "internal_error", 0), "保存に失敗")
    eq(await run_turn("discard", broken), (["start", "delta", "delta", "error"], "upstream_unavailable", 0), "discard")
    eq(await run_turn("partial", broken), (["start", "delta", "delta", "error"], "upstream_unavailable", 2), "partial")
    return ("保存できた → usage → done・2件／保存に失敗 → usage と done を送らず error（internal_error）・0件"
            "／途中の失敗（upstream_unavailable）→ discard 0件・partial 2件")


@dbcheck("P7 count_tokens の回数：1組ずつ・二分探索・近似で当たり（50往復・予算 200）")
async def _():
    messages = seed_messages(50)
    async with mock_llm() as (_, counter):
        results = {name: await fn(messages, counter, budget=200) for name, fn in (
            ("1組ずつ", fit_history_linear), ("二分探索", fit_history), ("近似で当たり", fit_history_fast))}
    eq({n: (len(f.dropped) // 2, f.input_tokens) for n, f in results.items()},
       {n: (47, 178) for n in results}, "落とした往復とトークン（3つとも同じ）")
    calls = {n: f.count_calls for n, f in results.items()}
    eq(calls, {"1組ずつ": 48, "二分探索": 7, "近似で当たり": 2}, "count_tokens の回数")
    return "47往復を落として 178 トークン（3つとも同じ）・count_tokens は 1組ずつ 48 回／二分探索 7 回／近似で当たり 2 回"


finish("session07-practice")
