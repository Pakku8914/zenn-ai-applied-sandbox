"""問題6の解答：偽物のデータと FakeProvider を dependency_overrides で差し込み、POST /api/suggest を単体テストする。

lifespan を回さないので、mockllm にもデータファイルにも触れない。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx2
import pytest

from .app import app, get_provider, get_store
from .providers import FakeItem, FakeProvider, ProviderError, Usage, fake_script
from .store import DataStore

STORE = DataStore.from_rows([
    {"id": "R901", "name": "テスト用カレー", "minutes": 30, "kcal": 500, "servings": 2,
     "ingredients": [{"name": "じゃがいも", "amount": 2, "unit": "個"}], "steps": ["煮る。"],
     "tags": ["洋食", "主菜"], "allergens": []},
])
OK = {"recipe_id": "R901", "question": "付け合わせは？"}


@pytest.fixture
def install() -> Iterator[Callable[..., FakeProvider]]:
    def _install(*scripts: list[FakeItem]) -> FakeProvider:
        fake = FakeProvider(*scripts)
        app.dependency_overrides[get_provider] = lambda: fake
        app.dependency_overrides[get_store] = lambda: STORE
        return fake

    yield _install
    app.dependency_overrides.clear()  # 次のテストに差し替えを持ち越さない


async def suggest(payload: dict) -> httpx2.Response:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post("/api/suggest", json=payload)


async def test_answer_comes_from_provider(install: Callable[..., FakeProvider]) -> None:
    fake = install(fake_script("ゆで卵を添えましょう。", usage=Usage(40, 12)))
    r = await suggest(OK)
    assert r.status_code == 200
    assert r.json() == {
        "answer": "ゆで卵を添えましょう。", "stop_reason": "end_turn", "provider": "fake",
        "usage": {"input_tokens": 40, "output_tokens": 12, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
        "request_id": r.headers["x-request-id"],
    }
    [req] = fake.requests
    assert req.messages == [{"role": "user", "content": "付け合わせは？"}]
    assert req.system is not None and "テスト用カレー" in req.system


async def test_unknown_recipe_does_not_call_llm(install: Callable[..., FakeProvider]) -> None:
    fake = install(fake_script("呼ばれないはず"))
    r = await suggest({**OK, "recipe_id": "R999"})
    assert (r.status_code, r.json()["error"]["type"]) == (404, "not_found")
    assert fake.requests == []


async def test_unknown_field_is_422_with_same_shape(install: Callable[..., FakeProvider]) -> None:
    fake = install(fake_script("呼ばれないはず"))
    r = await suggest({**OK, "temperature": 0.2})
    assert r.status_code == 422
    err = r.json()["error"]
    assert sorted(err) == ["message", "request_id", "type"] and err["type"] == "invalid_request"
    assert fake.requests == []


async def test_rate_limited_keeps_retry_after(install: Callable[..., FakeProvider]) -> None:
    install([ProviderError("rate_limited", provider="fake", status_code=429, retry_after=7)])
    r = await suggest(OK)
    assert (r.status_code, r.json()["error"]["type"], r.headers["retry-after"]) == (429, "rate_limited", "7")


async def test_retry_after_defaults_to_5(install: Callable[..., FakeProvider]) -> None:
    install([ProviderError("rate_limited", provider="fake", status_code=429)])
    r = await suggest(OK)
    assert (r.status_code, r.headers["retry-after"]) == (429, "5")
