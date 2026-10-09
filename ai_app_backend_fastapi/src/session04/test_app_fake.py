"""練習問題3の解答：FakeProvider を差し込んで POST /api/ask を単体テストする（ネットワークに出ない）。"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx2
import pytest

from .app import app, get_provider
from .providers import FakeItem, FakeProvider, ProviderError, Usage, fake_script


@pytest.fixture
def use_fake() -> Iterator[Callable[..., FakeProvider]]:
    def install(*scripts: list[FakeItem]) -> FakeProvider:
        fake = FakeProvider(*scripts)
        app.dependency_overrides[get_provider] = lambda: fake
        return fake

    yield install
    app.dependency_overrides.clear()


async def post(question: str) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
        return await c.post("/api/ask", json={"question": question})


async def test_answer_comes_from_provider(use_fake: Callable[..., FakeProvider]) -> None:
    use_fake(fake_script("塩炒めがおすすめです。", usage=Usage(12, 9)))
    r = await post("鶏むね肉で何を作れる？")
    assert r.status_code == 200
    assert r.json() == {
        "answer": "塩炒めがおすすめです。", "stop_reason": "end_turn", "provider": "fake",
        "usage": {"input_tokens": 12, "output_tokens": 9, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
        "request_id": r.headers["x-request-id"],
    }


async def test_question_is_sent_as_user_message(use_fake: Callable[..., FakeProvider]) -> None:
    fake = use_fake(fake_script("はい"))
    await post("キャベツの保存方法は？")
    assert [r.messages for r in fake.requests] == [[{"role": "user", "content": "キャベツの保存方法は？"}]]


async def test_provider_error_becomes_503_without_upstream_detail(use_fake: Callable[..., FakeProvider]) -> None:
    use_fake([ProviderError("rate_limited", provider="fake", status_code=429)])
    r = await post("献立を考えて")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["type"] == "upstream_unavailable"
    assert err["request_id"] == r.headers["x-request-id"]
    assert "fake" not in err["message"] and "429" not in err["message"]
