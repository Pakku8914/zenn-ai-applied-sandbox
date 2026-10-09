"""練習問題3：dependency_overrides でデータと時計を差し替えるテスト（pytest）。

    docker compose exec api pytest src/session02/test_q3_overrides.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx2
import pytest

from kondate.clock import FixedClock
from src.session02.app import app
from src.session02.deps import get_clock, get_store
from src.session02.store import DataStore

FAKE = DataStore.from_rows(
    [{"id": "R901", "name": "テスト用カレー", "minutes": 30, "kcal": 500, "servings": 2,
      "ingredients": [{"name": "じゃがいも", "amount": 2, "unit": "個"}], "steps": ["煮る。"],
      "tags": ["洋食", "主菜"], "allergens": []}],
    [{"id": "u900", "name": "テスト 太郎", "plan": "free", "household_size": 1, "allergies": ["卵"],
      "preferences": [], "created_at": "2026-09-01T09:00:00+09:00"}],
)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()  # 2026-10-02T18:00+09:00 で止まった時計


@pytest.fixture
async def client(clock: FixedClock) -> AsyncIterator[httpx2.AsyncClient]:
    app.dependency_overrides[get_store] = lambda: FAKE
    app.dependency_overrides[get_clock] = lambda: clock
    transport = httpx2.ASGITransport(app=app)  # lifespan は動かさない（store を差し替えるので要らない）
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()  # 次のテストに差し替えを持ち越さない


async def test_list_uses_fake_store(client: httpx2.AsyncClient) -> None:
    r = await client.get("/api/recipes")
    assert r.json() == {"total": 1, "recipes": [
        {"id": "R901", "name": "テスト用カレー", "minutes": 30, "kcal": 500, "tags": ["洋食", "主菜"]}]}


async def test_consultation_uses_fixed_clock(client: httpx2.AsyncClient) -> None:
    r = await client.post("/api/consultations", json={"user_id": "u900", "message": "卵なしで"})
    assert r.status_code == 201
    assert r.json()["received_at"] == "2026-10-02T18:00:00+09:00"
    assert r.json()["allergies"] == ["卵"]


async def test_clock_can_advance(client: httpx2.AsyncClient, clock: FixedClock) -> None:
    clock.advance(90)
    r = await client.post("/api/consultations", json={"user_id": "u900", "message": "90秒後"})
    assert r.json()["received_at"] == "2026-10-02T18:01:30+09:00"


async def test_real_user_is_not_in_fake_store(client: httpx2.AsyncClient) -> None:
    r = await client.post("/api/consultations", json={"user_id": "u001", "message": "こんにちは"})
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "not_found"
