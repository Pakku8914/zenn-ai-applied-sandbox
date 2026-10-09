"""Session 2（本文）の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session02

uvicorn を立てず、httpx2.ASGITransport で同じプロセスの中のアプリへリクエストを送る。
ASGITransport は lifespan を動かさないので、serve() の中で lifespan_context に入ってから送る。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from kondate.clock import FixedClock
from kondate.settings import Settings, get_settings
from kondate.verifykit import check, eq, finish
from src.session02.app import app
from src.session02.deps import get_clock, get_store
from src.session02.errors import install_error_handlers
from src.session02.store import DataStore

# 500 の検査で出るトレースバックを検証の出力に混ぜない（ログの扱いは構造化ログのセッションで）
logging.getLogger("kondate.errors").addHandler(logging.NullHandler())

RID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")

FAKE = DataStore.from_rows(
    [
        {"id": "R901", "name": "テスト用カレー", "minutes": 30, "kcal": 500, "servings": 2,
         "ingredients": [{"name": "じゃがいも", "amount": 2, "unit": "個"}], "steps": ["煮る。"],
         "tags": ["洋食", "主菜"], "allergens": []},
        {"id": "R902", "name": "テスト用サラダ", "minutes": 5, "kcal": 80, "servings": 2,
         "ingredients": [{"name": "レタス", "amount": 1, "unit": "玉"}], "steps": ["ちぎる。"],
         "tags": ["洋食", "副菜", "時短"], "allergens": []},
    ],
    [{"id": "u900", "name": "テスト 太郎", "plan": "free", "household_size": 1, "allergies": [],
      "preferences": [], "created_at": "2026-09-01T09:00:00+09:00"}],
)


@asynccontextmanager
async def serve(target: FastAPI = app) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=target, raise_app_exceptions=False)
    async with target.router.lifespan_context(target):
        async with httpx2.AsyncClient(transport=transport, base_url="http://kondate.test") as client:
            yield client


def ids(r: httpx2.Response) -> list[str]:
    return [x["id"] for x in r.json()["recipes"]]


def error_of(r: httpx2.Response) -> dict:
    err = r.json()["error"]
    assert RID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "ヘッダと本文の request_id")
    return err


@check("V1 GET /health が lifespan で読み込んだ件数を返す")
async def _():
    async with serve() as c:
        r = await c.get("/health")
    eq(r.status_code, 200, "status")
    eq(r.json(), {"status": "ok", "recipes": 120, "users": 5}, "本文")
    return r.text


@check("V2 GET /api/recipes/R001 がパスパラメータで1件を返す")
async def _():
    async with serve() as c:
        r = await c.get("/api/recipes/R001")
    eq(r.status_code, 200, "status")
    d = r.json()
    eq((d["name"], d["minutes"], d["kcal"], d["servings"], len(d["ingredients"]), d["allergens"]),
       ("鶏むね肉とキャベツの塩炒め", 15, 230, 2, 7, []), "R001")
    eq(d["ingredients"][0], {"name": "鶏むね肉", "amount": 250, "unit": "g"}, "1品目")
    return f"{d['id']} {d['name']}・{d['minutes']}分・{d['kcal']}kcal・材料{len(d['ingredients'])}品"


@check("V3 ingredient（部分一致）と max_minutes で絞り込み、一覧は5項目だけ返す")
async def _():
    async with serve() as c:
        r = await c.get("/api/recipes", params={"ingredient": "鶏むね肉"})
        r20 = await c.get("/api/recipes", params={"ingredient": "鶏むね肉", "max_minutes": 20})
    eq(r.json()["total"], 6, "鶏むね肉の件数")
    eq(ids(r), ["R001", "R009", "R025", "R028", "R051", "R052"], "鶏むね肉の id")
    eq(sorted(r.json()["recipes"][0]), ["id", "kcal", "minutes", "name", "tags"], "一覧の項目（response_model で絞られる）")
    eq(ids(r20), ["R001", "R009", "R025", "R052"], "20分以内")
    return "鶏むね肉 → 6件 / ＋max_minutes=20 → R001, R009, R025, R052"


@check("V4 tag を複数指定するとすべて含むもの（AND）になる")
async def _():
    async with serve() as c:
        one = await c.get("/api/recipes", params={"tag": "主菜"})
        both = await c.get("/api/recipes", params={"tag": ["主菜", "ヘルシー"]})
        mix = await c.get("/api/recipes", params={"ingredient": "鶏むね肉", "max_minutes": 20, "tag": ["中華", "ヘルシー"]})
    eq(one.json()["total"], 56, "主菜")
    eq(both.json()["total"], 20, "主菜 AND ヘルシー")
    eq(ids(mix), ["R001", "R009"], "鶏むね肉・20分以内・中華 AND ヘルシー")
    return "tag=主菜 → 56件 / tag=主菜&tag=ヘルシー → 20件 / 鶏むね肉・20分以内・中華&ヘルシー → R001, R009"


@check("V5 limit は返す件数だけを減らし、total は絞り込み後の全件数のまま")
async def _():
    async with serve() as c:
        r = await c.get("/api/recipes", params={"tag": "時短", "limit": 3})
        r15 = await c.get("/api/recipes", params={"max_minutes": 15})
    eq((r.json()["total"], ids(r)), (55, ["R001", "R002", "R003"]), "時短・limit=3")
    eq(r15.json()["total"], 55, "15分以内（時短タグと同じ集合）")
    return "tag=時短&limit=3 → total=55・R001, R002, R003 / max_minutes=15 → 55件"


@check("V6 入力の誤りは 422 invalid_request（共通のエラー本文・req_+ULID）")
async def _():
    cases = [
        ("/api/recipes", {"max_minutes": 0}, "max_minutes"),
        ("/api/recipes", {"tags": "中華"}, "tags"),
        ("/api/recipes/abc", None, "recipe_id"),
    ]
    async with serve() as c:
        for path, params, field in cases:
            r = await c.get(path, params=params)
            eq(r.status_code, 422, f"{path} {params}")
            err = error_of(r)
            eq((err["type"], err["message"]), ("invalid_request", f"入力値が正しくありません：{field}"), "本文")
    return "max_minutes=0 / tags=中華（綴り違い）/ recipe_id=abc → すべて 422 invalid_request"


@check("V7 404・405 も同じ形で返し、request_id はリクエストごとに変わる")
async def _():
    async with serve() as c:
        missing = await c.get("/api/recipes/R999")
        nope = await c.get("/api/nope")
        delete = await c.delete("/api/recipes/R001")
    got = [(r.status_code, error_of(r)["type"], error_of(r)["message"]) for r in (missing, nope, delete)]
    eq(got, [
        (404, "not_found", "レシピが見つかりません：R999"),
        (404, "not_found", "指定された URL は存在しません"),
        (405, "invalid_request", "この URL では、そのメソッドは使えません"),
    ], "404・405")
    assert "GET" in delete.headers["allow"], delete.headers
    eq(len({r.headers["x-request-id"] for r in (missing, nope, delete)}), 3, "request_id の重複")
    return "R999 → 404 / 未定義の URL → 404 / DELETE → 405（allow ヘッダ付き）・request_id は3件とも別"


@check("V8 POST /api/consultations が本文を検査し、注入した時計の時刻を返す")
async def _():
    app.dependency_overrides[get_clock] = lambda: FixedClock()
    try:
        async with serve() as c:
            ok = await c.post("/api/consultations", json={"user_id": "u001", "message": "  20分で作れる主菜は？  ", "max_minutes": 20})
            unknown = await c.post("/api/consultations", json={"user_id": "u999", "message": "こんにちは"})
            blank = await c.post("/api/consultations", json={"user_id": "u001", "message": "   "})
            extra = await c.post("/api/consultations", json={"user_id": "u001", "message": "こんにちは", "plan": "pro"})
    finally:
        app.dependency_overrides.clear()
    eq(ok.status_code, 201, f"status（本文 {ok.text}）")
    eq(ok.json(), {"user_id": "u001", "household_size": 2, "allergies": [], "message": "20分で作れる主菜は？",
                   "max_minutes": 20, "received_at": "2026-10-02T18:00:00+09:00"}, "本文")
    eq((unknown.status_code, error_of(unknown)["message"]), (404, "ユーザーが見つかりません：u999"), "u999")
    eq((blank.status_code, error_of(blank)["message"]), (422, "入力値が正しくありません：message"), "空白だけ")
    eq((extra.status_code, error_of(extra)["message"]), (422, "入力値が正しくありません：plan"), "余計な項目")
    return f"201 received_at={ok.json()['received_at']} / u999 → 404 / 空白だけ → 422 message / 余計な plan → 422 plan"


@check("V9 dependency_overrides でデータを差し替えられ、clear() で元に戻る")
async def _():
    app.dependency_overrides[get_store] = lambda: FAKE
    try:
        async with serve() as c:
            health = await c.get("/health")
            main = await c.get("/api/recipes", params={"tag": "主菜"})
    finally:
        app.dependency_overrides.clear()
    async with serve() as c:
        back = await c.get("/health")
    eq(health.json(), {"status": "ok", "recipes": 2, "users": 1}, "差し替え中")
    eq(ids(main), ["R901"], "差し替え中の主菜")
    eq(back.json()["recipes"], 120, "clear() のあと")
    return "差し替え中 recipes=2・主菜=R901 / clear() のあと recipes=120"


@check("V10 GET /health/upstream は共有クライアントで mockllm を確かめ、つながらなければ 503")
async def _():
    async with serve() as c:
        ok = await c.get("/health/upstream")
        app.dependency_overrides[get_settings] = lambda: Settings(mockllm_url="http://127.0.0.1:9")
        try:
            ng = await c.get("/health/upstream")
        finally:
            app.dependency_overrides.clear()
    eq((ok.status_code, ok.json()), (200, {"mockllm": "ok"}), "mockllm")
    err = error_of(ng)
    eq((ng.status_code, err["type"], err["message"]), (503, "upstream_unavailable", "AI が一時的に利用できません。時間をおいて再度お試しください。"), "接続先を壊したとき")
    return "mockllm → 200 {\"mockllm\":\"ok\"} / 接続先を差し替え → 503 upstream_unavailable"


async def timed(c: httpx2.AsyncClient, path: str, n: int = 5) -> float:
    started = time.perf_counter()
    rs = await asyncio.gather(*(c.get(path) for _ in range(n)))
    assert all(r.status_code == 200 for r in rs), [r.status_code for r in rs]
    return time.perf_counter() - started


@check("V11 async def の中の time.sleep だけがイベントループを止める")
async def _():
    async with serve() as c:
        blocking = await timed(c, "/demo/sleep/blocking")
        others = {name: await timed(c, f"/demo/sleep/{name}") for name in ("async", "thread", "offload")}
    assert blocking >= 0.9, f"blocking={blocking:.2f}s（直列なら 5×0.2=1.0 秒）"
    for name, sec in others.items():
        assert sec < 0.6, f"{name}={sec:.2f}s"
    return "5件同時：blocking は直列（0.9 秒以上）・async / thread / offload は並行（0.6 秒未満）"


@check("V12 lifespan：起動時に store と共有クライアントを用意し、終了時に閉じる")
async def _():
    async with app.router.lifespan_context(app):
        eq(len(app.state.store.recipes), 120, "起動後の store")
        http = app.state.http
        eq(http.is_closed, False, "起動中のクライアント")
    eq(http.is_closed, True, "終了後のクライアント")
    return "起動時 store=120件・http を開く → 終了時 http.is_closed=True"


@check("V13 想定外の例外は 500 internal_error にし、生のエラー文を返さない")
async def _():
    boom = FastAPI()
    install_error_handlers(boom)

    @boom.get("/boom")
    async def _boom() -> dict:
        raise RuntimeError("DB に接続できません password=kondate host=postgres")

    async with serve(boom) as c:
        r = await c.get("/boom")
    eq(r.status_code, 500, "status")
    err = error_of(r)
    eq((err["type"], err["message"]), ("internal_error", "サーバー内部でエラーが発生しました"), "本文")
    assert "password" not in r.text, r.text
    return "500 internal_error「サーバー内部でエラーが発生しました」（password などの生の文は含まない）"


finish("session02")
