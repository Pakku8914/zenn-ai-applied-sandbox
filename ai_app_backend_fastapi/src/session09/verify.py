"""Session 9（API キー認証とユーザー単位の分離）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session09/verify.py
    docker compose exec api bash verify-all.sh src/session09   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from kondate.clock import FixedClock
from kondate.db import SessionLocal
from kondate.verifykit import eq, finish
from src.session09 import keys, repo
from src.session09.app import AuthSettings, app, get_auth_settings
from src.session09.harness import (alembic, assert_unauthorized, bearer, capture_logs, client_for, dbcheck, issue,
                                   reasons, reset_schema, scalar, upgraded)
from src.session09.models import new_id
from src.session09.users import seed_users


@dbcheck("V1 alembic upgrade head でスキーマ s09 に users と api_keys ができる")
async def _():
    await reset_schema()
    log = await asyncio.to_thread(alembic, "upgrade", "head")
    eq(upgraded(log), ["0001", "0002"], "適用されたリビジョン")
    tables = await scalar("SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM information_schema.tables "
                          "WHERE table_schema = 's09'")
    eq(tables, "alembic_version, api_keys, conversations, messages, users", "s09 のテーブル")
    return f"0001 → 0002・テーブル {tables}"


@dbcheck("V2 alembic check：モデルとマイグレーションに差がない")
async def _():
    out = await asyncio.to_thread(alembic, "check")
    assert "No new upgrade operations detected." in out, out
    return "No new upgrade operations detected."


@dbcheck("V3 users.json の5人を登録する（2回目は0件）")
async def _():
    async with SessionLocal() as s:
        first = await seed_users(s)
        second = await seed_users(s)
        await s.commit()
    plans = await scalar("SELECT string_agg(plan || ' ' || n, ' / ' ORDER BY plan) FROM "
                         "(SELECT plan, count(*) AS n FROM s09.users GROUP BY plan) t")
    eq((first, second, plans), (5, 0, "free 3 / pro 2"), "登録数と plan の内訳")
    return "1回目 5件・2回目 0件・free 3 / pro 2"


@dbcheck("V4 発行：平文は kd_ + 43文字、DB には SHA-256 と先頭8文字だけ")
async def _():
    issued = await issue("u001", FixedClock(), name="ノートPC")
    assert keys.KEY_PATTERN.fullmatch(issued.key), "キーの形式"
    eq(len(issued.key), 46, "キーの長さ")
    stored = await scalar("SELECT prefix || ' ' || key_hash FROM s09.api_keys WHERE id::text = :id", id=issued.id)
    eq(stored, f"{issued.key[:8]} {hashlib.sha256(issued.key.encode()).hexdigest()}", "保存した prefix と key_hash")
    row_json = await scalar("SELECT row_to_json(k)::text FROM s09.api_keys k WHERE id::text = :id", id=issued.id)
    assert issued.key not in row_json, "行のどこかに平文がある"
    assert issued.key not in repr(issued), "repr に平文が出ている"
    return "46文字（kd_ + 43）・保存は先頭8文字と SHA-256（64桁）・行にも repr にも平文なし"


@dbcheck("V5 正しいキーなら GET /api/me が 200（方式名 bearer は大文字小文字を区別しない）")
async def _():
    clock = FixedClock()
    issued = await issue("u001", clock)
    async with client_for(app, clock) as c:
        r = await c.get("/api/me", headers=bearer(issued.key))
        lower = await c.get("/api/me", headers={"Authorization": f"bearer {issued.key}"})
    eq((r.status_code, lower.status_code), (200, 200), "status")
    eq(r.json(), {"id": "u001", "name": "佐藤 美咲", "plan": "free"}, "本文")
    return f"200 {json.dumps(r.json(), ensure_ascii=False)}"


@dbcheck("V6 認証の失敗は5通りとも同じ 401 unauthorized（WWW-Authenticate: Bearer）")
async def _():
    cap = capture_logs()
    cases = [{}, {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer"},
             {"Authorization": "Bearer abc"}, bearer(keys.generate_key())]
    async with client_for(app, FixedClock()) as c:
        for headers in cases:
            assert_unauthorized(await c.get("/api/me", headers=headers))
    eq(reasons(cap), ["no_bearer", "no_bearer", "no_bearer", "malformed", "unknown"], "ログに残る理由")
    return "ヘッダなし・Basic・Bearer のみ・形式違い・未登録 → すべて同じ本文（理由はログだけ: no_bearer×3, malformed, unknown）"


@dbcheck("V7 他人の会話は GET・PATCH・DELETE とも 404（存在しない会話と同じ）")
async def _():
    clock = FixedClock()
    k1, k2 = await issue("u001", clock), await issue("u002", clock)
    async with client_for(app, clock) as c:
        r = await c.post("/api/conversations", json={"title": "今週の夕飯"}, headers=bearer(k1.key))
        eq(r.status_code, 201, f"作成（{r.text}）")
        cid = r.json()["id"]
        async with SessionLocal() as s:
            await repo.append_turn(s, "u001", cid, user_content="一日目の献立は？",
                                   assistant_content=[{"type": "text", "text": "鶏むね肉とキャベツの塩炒めです。"}])
            hijack = await repo.append_turn(s, "u002", cid, user_content="横から書き込む",
                                            assistant_content=[{"type": "text", "text": "…"}])
            await s.commit()
        url = f"/api/conversations/{cid}"
        others = [await c.get(url, headers=bearer(k2.key)),
                  await c.patch(url, json={"title": "乗っ取り"}, headers=bearer(k2.key)),
                  await c.delete(url, headers=bearer(k2.key))]
        missing = await c.get(f"/api/conversations/{new_id()}", headers=bearer(k1.key))
        their_list = (await c.get("/api/conversations", headers=bearer(k2.key))).json()
        mine = (await c.get(url, headers=bearer(k1.key))).json()
    eq([(r.status_code, r.json()["error"]["type"]) for r in others], [(404, "not_found")] * 3, "u002 からの操作")
    eq(others[0].json()["error"]["message"], missing.json()["error"]["message"], "存在しない会話と同じ文面")
    eq((hijack, their_list), (None, []), "u002 の append_turn と一覧")
    eq((mine["title"], len(mine["messages"])), ("今週の夕飯", 2), "u001 の会話")
    return "u002 から GET・PATCH・DELETE → 404 ×3（存在しない ID と同じ本文）・u002 の一覧 0件・u001 の会話は発言2件ごと無傷"


@dbcheck("V8 持ち主は本文ではなく認証から決める（本文の user_id は 422）")
async def _():
    clock = FixedClock()
    k1 = await issue("u001", clock)
    async with client_for(app, clock) as c:
        forged = await c.post("/api/conversations", json={"title": "x", "user_id": "u002"}, headers=bearer(k1.key))
        anonymous = await c.post("/api/conversations", json={"title": "x"})
    eq((forged.status_code, forged.json()["error"]["type"]), (422, "invalid_request"), "本文に user_id")
    eq(anonymous.status_code, 401, "キーなし")
    return "本文に user_id → 422 invalid_request・キーなし → 401"


@dbcheck("V9 失効：DELETE /api/keys/{id} の直後からそのキーは 401、他人のキーは 404")
async def _():
    clock = FixedClock()
    a = await issue("u003", clock, name="ノートPC")
    clock.advance(1)
    b = await issue("u003", clock, name="古いスマホ")
    theirs = await issue("u005", clock)
    cap = capture_logs()
    async with client_for(app, clock) as c:
        first = await c.delete(f"/api/keys/{b.id}", headers=bearer(a.key))
        assert_unauthorized(await c.get("/api/me", headers=bearer(b.key)))
        still = await c.get("/api/me", headers=bearer(a.key))
        other = await c.delete(f"/api/keys/{theirs.id}", headers=bearer(a.key))
        again = await c.delete(f"/api/keys/{b.id}", headers=bearer(a.key))
        listed = [(k["name"], k["status"]) for k in (await c.get("/api/keys", headers=bearer(a.key))).json()]
    eq((first.status_code, still.status_code, other.status_code, again.status_code), (204, 200, 404, 204),
       "失効・残ったキー・他人のキー・2回目の失効")
    eq(listed, [("ノートPC", "active"), ("古いスマホ", "revoked")], "キーの一覧")
    eq(reasons(cap), ["revoked"], "ログに残る理由")
    return "失効 204 → 失効したキー 401・残ったキー 200・他人のキー 404・2回目も 204（冪等）"


@dbcheck("V10 ローテーション：猶予（3600秒）の間は新旧どちらも使え、期限の時刻ちょうどに旧キーが 401")
async def _():
    clock = FixedClock()
    old = await issue("u004", clock, name="サーバA")
    clock.advance(600)  # 18:10 にローテーションする
    cap = capture_logs()
    async with client_for(app, clock) as c:
        app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(api_key_rotation_grace_seconds=3600)
        r = await c.post(f"/api/keys/{old.id}/rotate", headers=bearer(old.key))
        eq((r.status_code, r.headers.get("cache-control")), (201, "no-store"), f"ローテーション（{r.text}）")
        new = r.json()["api_key"]
        assert keys.KEY_PATTERN.fullmatch(new) and new != old.key, "新しいキー"
        listed = [(k["status"], k["expires_at"]) for k in (await c.get("/api/keys", headers=bearer(new))).json()]
        clock.advance(3599)  # 19:09:59
        before = [(await c.get("/api/me", headers=bearer(k))).status_code for k in (old.key, new)]
        clock.advance(1)  # 19:10:00
        after = [(await c.get("/api/me", headers=bearer(k))).status_code for k in (old.key, new)]
        twice = await c.post(f"/api/keys/{old.id}/rotate", headers=bearer(new))
    eq(listed, [("active", "2026-10-02T19:10:00+09:00"), ("active", None)], "ローテーション直後の一覧")
    eq((before, after, twice.status_code), ([200, 200], [401, 200], 404), "19:09:59・19:10:00・期限切れの再ローテーション")
    eq(reasons(cap), ["expired"], "ログに残る理由")
    return "18:10 に実行 → 旧キーの期限 19:10:00+09:00・19:09:59 は新旧とも 200・19:10:00 は旧 401（expired）／新 200"


@dbcheck("V11 POST /api/keys：平文は発行の応答（no-store）にだけ現れ、一覧には出ない")
async def _():
    clock = FixedClock()
    first = await issue("u005", clock, name="最初のキー")
    async with client_for(app, clock) as c:
        r = await c.post("/api/keys", json={"name": "スマホ", "expires_in_days": 30}, headers=bearer(first.key))
        body = r.json()
        listed = await c.get("/api/keys", headers=bearer(body["api_key"]))
    eq((r.status_code, r.headers.get("cache-control")), (201, "no-store"), "発行の応答")
    eq((sorted(body), body["expires_at"]), (["api_key", "expires_at", "id", "name", "prefix"],
                                            "2026-11-01T18:00:00+09:00"), "発行の本文")
    eq(sorted(listed.json()[0]), ["created_at", "expires_at", "id", "name", "prefix", "revoked_at", "status"],
       "一覧の項目")
    for secret in (first.key, body["api_key"], keys.hash_key(body["api_key"])):
        assert secret not in listed.text, "一覧に平文かハッシュが出ている"
    return "201・Cache-Control: no-store・期限 2026-11-01T18:00:00+09:00・一覧は7項目で平文もハッシュも含まない"


@dbcheck("V12 ログとエラー本文にキーが出ない（ログは理由と先頭8文字だけ）")
async def _():
    clock = FixedClock()
    good, revoked = await issue("u002", clock), await issue("u002", clock)
    async with SessionLocal() as s:
        await keys.revoke_key(s, "u002", revoked.id, now=clock.now())
        await s.commit()
    unknown, malformed = keys.generate_key(), "kd_" + "x" * 10
    cap = capture_logs()
    async with client_for(app, clock) as c:
        responses = [await c.get("/api/me", headers=bearer(k)) for k in (unknown, revoked.key, malformed)]
        responses.append(await c.post("/api/conversations", json={"title": good.key * 10}, headers=bearer(good.key)))
    eq([r.status_code for r in responses], [401, 401, 401, 422], "status")
    secrets = (unknown, revoked.key, malformed, good.key)
    for text in [*cap.lines, *(r.text for r in responses)]:
        assert not any(s in text for s in secrets), f"キーが出ている: {text}"
    eq(reasons(cap), ["unknown", "revoked", "malformed"], "ログに残る理由")
    eq([f"key_prefix={unknown[:8]}" in cap.lines[0], f"key_prefix={revoked.key[:8]}" in cap.lines[1],
        "key_prefix=-" in cap.lines[2]], [True, True, True], "ログの key_prefix")
    return "ログ3行（unknown・revoked・malformed）と応答4件のどこにも平文なし・形式違いは先頭も記録しない"


finish("session09")
