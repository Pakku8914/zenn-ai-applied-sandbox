"""Session 9 練習問題の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session09
"""

from __future__ import annotations

import hashlib
import inspect
import logging
from datetime import timedelta

from kondate.cache import make_redis
from kondate.clock import JST, FixedClock
from kondate.db import SessionLocal
from kondate.verifykit import check, eq, finish
from src.session09 import keys, repo
from src.session09.harness import capture_logs, dbcheck, issue, prepare_db, scalar
from src.session09.models import new_id
from src.session09.q1_record import display_hint, new_key_record
from src.session09.q2_bearer import key_matches, parse_bearer
from src.session09.q3_messages import count_messages, get_message
from src.session09.q4_revoke_all import revoke_all
from src.session09.q5_redact import RedactSecrets, install_redaction
from src.session09.q6_cache import CachedAuthenticator


@check("P1 保存する行と平文を分けて作る（100本）")
def _():
    now = FixedClock().now()
    made = [new_key_record("u001", now) for _ in range(100)]
    eq(len({k for k, _ in made}), 100, "平文が重複しない")
    for key, record in made:
        assert keys.KEY_PATTERN.fullmatch(key), key[:8]
        eq(sorted(record), ["created_at", "key_hash", "prefix", "user_id"], "行の項目")
        eq((record["prefix"], record["key_hash"], record["created_at"]),
           (key[:8], hashlib.sha256(key.encode()).hexdigest(), now), "行の値")
        assert key not in str(record), "行に平文が入っている"
        eq(display_hint(record), key[:8] + "…", "見分け用の表記")
    return "100本とも kd_ + 43文字・重複なし・行は4項目で平文を含まない・表記は先頭8文字＋…"


@check("P2 Bearer の取り出し（9ケース）と定数時間の照合")
def _():
    key = keys.generate_key()
    cases = [(None, None), ("", None), (f"Bearer {key}", key), (f"bearer {key}", key), (f"BEARER {key}", key),
             (f"Bearer  {key}", key), ("Basic dXNlcjpwYXNz", None), ("Bearer", None), (f"Bearer {key} extra", None)]
    for i, (given, expected) in enumerate(cases, 1):
        eq(parse_bearer(given), expected, f"ケース{i}")
    stored = keys.hash_key(key)
    eq((key_matches(key, stored), key_matches(keys.generate_key(), stored)), (True, False), "照合")
    src = inspect.getsource(key_matches)
    assert "compare_digest" in src and "==" not in src, "== で比べている"
    return "9ケースすべて期待どおり・照合は一致 True／別のキー False（compare_digest を使用）"


@dbcheck("P3 発言の取得と件数にも持ち主の条件を付ける")
async def _():
    await prepare_db()
    async with SessionLocal() as s:
        mine = await repo.create_conversation(s, user_id="u001", title="一日目")
        theirs = await repo.create_conversation(s, user_id="u002", title="二日目")
        turn = await repo.append_turn(s, "u001", mine.id, user_content="卵で何か作れる？",
                                      assistant_content=[{"type": "text", "text": "卵焼きはどうですか。"}])
        for text in ("豆腐で何か作れる？", "副菜は？"):
            await repo.append_turn(s, "u002", theirs.id, user_content=text,
                                   assistant_content=[{"type": "text", "text": "考えますね。"}])
        await s.commit()
        message_id = turn[1].id
        got = (await get_message(s, "u001", message_id), await get_message(s, "u002", message_id),
               await get_message(s, "u001", new_id()))
        counts = (await count_messages(s, "u001"), await count_messages(s, "u002"))
    eq((got[0].id if got[0] else None, got[1], got[2]), (message_id, None, None), "持ち主・他人・存在しない")
    eq(counts, (2, 4), "発言の数")
    return "持ち主は取得できる・他人と存在しない ID は None・件数は u001 2件／u002 4件"


@dbcheck("P4 一括失効：使っているキー以外を止め、既に失効したキーの時刻は変えない")
async def _():
    clock = FixedClock()
    a, _, _, d = [await issue("u003", clock, name=n) for n in ("いま使用中", "スマホ", "サーバ", "古いキー")]
    keep_other = await issue("u004", clock)
    async with SessionLocal() as s:
        await keys.revoke_key(s, "u003", d.id, now=clock.now())  # 18:00 に失効済み
        await s.commit()
    clock.advance(1800)
    async with SessionLocal() as s:
        first = await revoke_all(s, "u003", now=clock.now(), keep_key_id=a.id)
        second = await revoke_all(s, "u003", now=clock.now(), keep_key_id=a.id)
        await s.commit()
        statuses = {k.name: keys.key_status(k, clock.now()) for k in await keys.list_keys(s, "u003")}
        other = (await keys.authenticate(s, keep_other.key, now=clock.now())).reason
    d_revoked = await scalar("SELECT revoked_at FROM s09.api_keys WHERE id::text = :id", id=d.id)
    eq((first, second), (2, 0), "失効させた本数（1回目・2回目）")
    eq(statuses, {"いま使用中": "active", "スマホ": "revoked", "サーバ": "revoked", "古いキー": "revoked"},
       "u003 のキー")
    eq((other, d_revoked.astimezone(JST).isoformat()), ("ok", "2026-10-02T18:00:00+09:00"), "u004 と古いキー")
    return "1回目 2本・2回目 0本・使用中のキーだけ active・u004 は影響なし・古いキーの失効時刻は 18:00 のまま"


@check("P5 ログに混ざったキーを伏せる（ハンドラに付けたフィルタ）")
def _():
    key = keys.generate_key()
    log = logging.getLogger("kondate.session09.q5")

    cap = capture_logs()  # 親ロガー kondate.session09 のハンドラ
    parent = logging.getLogger("kondate.session09")
    on_logger = RedactSecrets()
    parent.addFilter(on_logger)  # よくある間違い：ロガーに付ける
    log.info("auth key=%s", key)
    parent.removeFilter(on_logger)
    eq(key in cap.lines[0], True, "ロガーに付けたフィルタは、子から伝わった記録に効かない")

    cap = install_redaction(capture_logs())
    log.info("auth key=%s", key)
    log.warning(f"Authorization: Bearer {key}")
    try:
        raise ValueError(f"キーの照合に失敗しました: {key}")
    except ValueError:
        log.exception("unexpected_error")
    eq(len(cap.lines), 3, "記録の数")
    assert not any(key in line for line in cap.lines), "平文が残っている"
    eq([key[:8] + "…" in cap.lines[0], "Bearer ***" in cap.lines[1], key[:8] + "…" in cap.lines[2]],
       [True, True, True], "伏せた形")
    return "ロガーに付けると子の記録に効かない／ハンドラに付けると3通り（%s の引数・Bearer・例外の本文）とも伏せる"


@dbcheck("P6 照合結果を Redis に覚える：2回目は DB を引かず、失効と期限は即座に効く")
async def _():
    redis = make_redis()
    try:
        async for name in redis.scan_iter("s09:*"):
            await redis.delete(name)
        clock = FixedClock()
        cached = CachedAuthenticator(redis, ttl_seconds=60)
        k = await issue("u002", clock)
        async with SessionLocal() as s:
            u1 = await cached.authenticate(s, k.key, now=clock.now())
            u2 = await cached.authenticate(s, k.key, now=clock.now())
        eq((u1.id, u2.id, cached.db_lookups), ("u002", "u002", 1), "2回照合して DB は1回")
        ttl = await redis.ttl(cached.cache_key(keys.hash_key(k.key)))
        assert 0 < ttl <= 60, ttl
        async with SessionLocal() as s:
            revoked = await cached.revoke_and_forget(s, "u002", k.id, now=clock.now())
        async with SessionLocal() as s:
            after = await cached.authenticate(s, k.key, now=clock.now())
        eq((revoked, after, cached.db_lookups), (True, None, 2), "失効の直後")

        short = await issue("u002", clock, ttl=timedelta(seconds=30))
        async with SessionLocal() as s:
            first = await cached.authenticate(s, short.key, now=clock.now())
            short_ttl = await redis.ttl(cached.cache_key(keys.hash_key(short.key)))
            clock.advance(30)
            expired = await cached.authenticate(s, short.key, now=clock.now())
        eq((first.id, expired, cached.db_lookups), ("u002", None, 3), "期限 30 秒のキー")
        assert 0 < short_ttl <= 30, short_ttl
        stored = [name async for name in redis.scan_iter("s09:*")]
        values = [await redis.get(n) or "" for n in stored]
        assert not any(sec in t for sec in (k.key, short.key) for t in [*stored, *values]), "Redis に平文がある"
    finally:
        await redis.aclose()
    return "2回目は DB を引かない（照合 1回）・失効の直後に拒否・期限 30 秒のキーは TTL 30 秒以内で、Clock を 30 秒進めると拒否"


finish("session09-practice")
