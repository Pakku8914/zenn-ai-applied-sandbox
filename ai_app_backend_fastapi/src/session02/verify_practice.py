"""Session 2（練習問題の解答）の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session02
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from fastapi import FastAPI

from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session02.answers_app import app
from src.session02.deps import get_store
from src.session02.q6_lifespan_check import create_app

logging.getLogger("kondate.errors").addHandler(logging.NullHandler())

RID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")
DATA_DIR = Path(get_settings().data_dir)


@asynccontextmanager
async def serve(target: FastAPI = app) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=target, raise_app_exceptions=False)
    async with target.router.lifespan_context(target):
        async with httpx2.AsyncClient(transport=transport, base_url="http://kondate.test") as client:
            yield client


def ids(r: httpx2.Response) -> list[str]:
    return [x["id"] for x in r.json()["recipes"]]


def error_of(r: httpx2.Response) -> tuple[int, str, str]:
    err = r.json()["error"]
    assert RID.match(err["request_id"]), err["request_id"]
    return r.status_code, err["type"], err["message"]


@check("P1 GET /api/users/{user_id} は公開してよい4項目だけを返す")
async def _():
    async with serve() as c:
        ok = await c.get("/api/users/u002")
        missing = await c.get("/api/users/u999")
        bad = await c.get("/api/users/U1")
    eq(ok.json(), {"id": "u002", "name": "鈴木 健太", "plan": "pro", "household_size": 4}, "u002")
    eq(error_of(missing), (404, "not_found", "ユーザーが見つかりません：u999"), "u999")
    eq(error_of(bad), (422, "invalid_request", "入力値が正しくありません：user_id"), "U1")
    return "u002 → id・name・plan・household_size / u999 → 404 / U1 → 422 user_id"


@check("P2 exclude_allergen（複数可）と sort=minutes を足した一覧")
async def _():
    async with serve() as c:
        no_wheat = await c.get("/api/recipes", params={"ingredient": "鶏むね肉", "exclude_allergen": "小麦"})
        no_milk = await c.get("/api/recipes", params={"ingredient": "鶏むね肉", "exclude_allergen": ["乳"]})
        by_min = await c.get("/api/recipes", params={"ingredient": "鶏むね肉", "sort": "minutes"})
        bad = await c.get("/api/recipes", params={"sort": "kcal"})
    eq(ids(no_wheat), ["R001"], "小麦を除く")
    eq(ids(no_milk), ["R001", "R009", "R028", "R051", "R052"], "乳を除く")
    eq(ids(by_min), ["R001", "R009", "R025", "R052", "R051", "R028"], "minutes 昇順・同じなら id 順")
    eq(error_of(bad), (422, "invalid_request", "入力値が正しくありません：sort"), "sort=kcal")
    return "小麦を除く → R001 / 乳を除く → 5件 / sort=minutes → R001, R009, R025, R052, R051, R028 / sort=kcal → 422"


@check("P3 dependency_overrides を使う pytest が4件とも通る")
def _():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "src/session02/test_q3_overrides.py", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout}\n{r.stderr}")
    assert re.search(r"\b4 passed\b", r.stdout), r.stdout
    return "pytest：4 passed"


async def timed(c: httpx2.AsyncClient, path: str, n: int = 5) -> float:
    started = time.perf_counter()
    rs = await asyncio.gather(*(c.get(path) for _ in range(n)))
    assert all(r.status_code == 200 for r in rs), [r.status_code for r in rs]
    return time.perf_counter() - started


@check("P4 直したルートはイベントループを止めない")
async def _():
    async with serve() as c:
        count = await c.get("/api/recipes/count")
        up = await c.get("/api/upstream")
        slow = await timed(c, "/api/tips/slow")
        thread = await timed(c, "/api/tips/thread")
    eq(count.json(), {"count": 120}, "count")
    eq(up.json(), {"mockllm": "ok"}, "upstream")
    assert slow < 0.9 and thread < 0.9, f"slow={slow:.2f}s thread={thread:.2f}s（直列なら 1.5 秒）"
    return "count=120・upstream=ok・tips/slow と tips/thread は5件同時でも並行（0.9 秒未満）"


class BrokenStore:
    def get_recipe(self, recipe_id: str) -> dict:
        raise RuntimeError("could not connect: password=kondate host=postgres")


@check("P5 ドメイン例外は 404 not_found、想定外の例外は生の文を出さずに 500")
async def _():
    async with serve() as c:
        ok = await c.get("/api/recipes/R001/steps")
        missing = await c.get("/api/recipes/R999/steps")
        app.dependency_overrides[get_store] = lambda: BrokenStore()
        try:
            broken = await c.get("/api/recipes/R001/steps")
        finally:
            app.dependency_overrides.clear()
    eq((ok.json()["name"], len(ok.json()["steps"])), ("鶏むね肉とキャベツの塩炒め", 4), "R001 の手順")
    eq(error_of(missing), (404, "not_found", "レシピが見つかりません：R999"), "R999")
    eq(error_of(broken), (500, "internal_error", "サーバー内部でエラーが発生しました"), "壊れた store")
    assert "password" not in broken.text, broken.text
    return "R001 → 手順4つ / R999 → 404 not_found / 壊れた store → 500 internal_error（password を含まない）"


@check("P6 lifespan が起動時にデータを検査し、壊れていたら起動を止める")
async def _():
    good = create_app(DATA_DIR)
    async with serve(good) as c:
        health = await c.get("/health")
    eq(health.json(), {"status": "ok", "recipes": 120}, "正しいデータ")
    eq(good.state.http.is_closed, True, "終了後のクライアント")

    messages = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "recipes.json").write_bytes((DATA_DIR / "recipes.json").read_bytes() + b" ")
        shutil.copy(DATA_DIR / "users.json", tmp / "users.json")
        (tmp / "missing").mkdir()
        shutil.copy(DATA_DIR / "recipes.json", tmp / "missing" / "recipes.json")
        for target in (tmp, tmp / "missing"):
            broken = create_app(target)
            try:
                async with broken.router.lifespan_context(broken):
                    pass
            except RuntimeError as e:
                messages.append(str(e))
            eq(hasattr(broken.state, "http"), False, "起動に失敗したときクライアントを作っていない")
    eq(messages, ["共通データのハッシュが一致しません：recipes.json", "共通データが見つかりません：users.json"], "失敗の理由")
    return "正しいデータ → 起動・終了時に close / 1バイト違い → ハッシュ不一致 / users.json なし → 見つかりません"


finish("session02-practice")
