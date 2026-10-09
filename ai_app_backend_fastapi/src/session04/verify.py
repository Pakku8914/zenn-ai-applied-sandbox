"""Session 4（プロバイダ差し替え層）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session04/verify.py
    docker compose exec api bash verify-all.sh src/session04   # 練習問題の検証も含めて実行
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import httpx2

from kondate.verifykit import check, eq, finish
from src.session04.app import UPSTREAM_MESSAGE, app, get_provider
from src.session04.contract_kit import (PROMPT, SEARCH_INPUT, TEXT_REQ, TOOL_REQ, TOOL_RESULT, event_shape,
                                        provider_under_test)
from src.session04.providers import (ChatRequest, ChatResult, Done, FakeProvider, LLMProvider, ProviderError,
                                     TextDelta, ToolCallDelta, ToolCallDone, ToolCallStart, Usage, accumulate,
                                     assistant_message, fake_script)

ROOT = Path(__file__).resolve().parents[2]
REAL = ["anthropic", "openai"]
logging.getLogger("kondate.session04").addHandler(logging.NullHandler())  # 503 の警告ログ（ID 入り）を出さない


def run_pytest(path: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", path, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout[-3000:]}{r.stderr[-2000:]}")
    m = re.search(r"(\d+) passed", lines[-1] if lines else "")
    assert m, lines[-1:]
    return int(m.group(1))


@check("V1 providers.py の型と名前が API 契約②どおり")
def _():
    expected = {
        Usage: ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"],
        ChatRequest: ["messages", "system", "tools", "max_tokens", "model"],
        ChatResult: ["text", "tool_calls", "stop_reason", "usage", "request_id"],
        TextDelta: ["text"], ToolCallStart: ["id", "name"], ToolCallDelta: ["id", "partial_json"],
        ToolCallDone: ["id", "name", "input"], Done: ["stop_reason", "usage"],
    }
    for cls, names in expected.items():
        eq([f.name for f in fields(cls)], names, cls.__name__)
    req = ChatRequest(messages=[])
    eq((req.system, req.tools, req.max_tokens, req.model), (None, [], 1024, None), "ChatRequest の既定値")
    try:
        Usage(1, 2).input_tokens = 3  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Usage が frozen になっていない")
    return f"{len(expected)} 個の型のフィールドが一致・frozen"


@check("V2 3つの実装が LLMProvider を満たす")
async def _():
    names = []
    for name in [*REAL, "fake"]:
        async with provider_under_test(name, fake_script("x")) as p:
            assert isinstance(p, LLMProvider), name
            names.append(p.name)
    eq(names, ["anthropic", "openai", "fake"], "name")
    return "・".join(names)


@check("V3 complete()：テキストの応答が2つの SDK で同じ形になる")
async def _():
    got = {}
    for name in REAL:
        async with provider_under_test(name) as p:
            r = await p.complete(TEXT_REQ)
        got[name] = (r.stop_reason, r.usage, len(r.text), r.tool_calls, (r.request_id or "").startswith("req_mock_"))
    eq(got["openai"], got["anthropic"], "anthropic と openai の差")
    eq(got["anthropic"], ("end_turn", Usage(34, 181), 192, [], True), "値")
    return "stop_reason=end_turn・input_tokens=34・output_tokens=181・192 字（anthropic と openai で一致）"


@check("V4 stream()：テキストのイベント列が同じで、畳むと complete() と一致する")
async def _():
    shapes = {}
    for name in REAL:
        async with provider_under_test(name) as p:
            r = await p.complete(TEXT_REQ)
            events = [ev async for ev in p.stream(TEXT_REQ)]
        eq(accumulate(events), replace(r, request_id=None), f"{name}：畳んだ結果")
        shapes[name] = event_shape(events)
    eq(shapes, {n: "TextDelta×32 → Done" for n in REAL}, "イベント列")
    return "TextDelta×32 → Done（anthropic・openai）"


@check("V5 stream()：ツール呼び出しも同じイベント列に正規化される")
async def _():
    shapes, dones, ids = {}, {}, {}
    for name in REAL:
        async with provider_under_test(name) as p:
            events = [ev async for ev in p.stream(TOOL_REQ)]
        shapes[name] = event_shape(events)
        done = next(ev for ev in events if isinstance(ev, ToolCallDone))
        dones[name] = (done.name, done.input, events[-1].stop_reason, events[-1].usage.output_tokens)
        ids[name] = done.id
    expected_shape = "TextDelta×3 → ToolCallStart → ToolCallDelta×4 → ToolCallDone → Done"
    eq(shapes, {n: expected_shape for n in REAL}, "イベント列")
    eq(dones["openai"], dones["anthropic"], "ToolCallDone と Done の差")
    eq(dones["anthropic"], ("search_recipes", SEARCH_INPUT, "tool_use", 42), "値")
    eq(ids["anthropic"].removeprefix("toolu_mock_"), ids["openai"].removeprefix("call_"), "id のハッシュ部分")
    assert ids["anthropic"] != ids["openai"]
    return f"{expected_shape}・search_recipes {json.dumps(SEARCH_INPUT, ensure_ascii=False)}・output_tokens=42"


@check("V6 tool_result を返す2回目も、OpenAI 形式に変換して同じ結果になる")
async def _():
    got = {}
    for name in REAL:
        async with provider_under_test(name) as p:
            first = await p.complete(TOOL_REQ)
            tool_result = {"type": "tool_result", "tool_use_id": first.tool_calls[0].id, "content": TOOL_RESULT}
            second = await p.complete(replace(TOOL_REQ, messages=[
                *TOOL_REQ.messages, assistant_message(first), {"role": "user", "content": [tool_result]}]))
        got[name] = [(c.name, c.input) for c in second.tool_calls]
    eq(got, {n: [("get_recipe", {"recipe_id": "R001"})] for n in REAL}, "2回目のツール呼び出し")
    return '2回目は get_recipe {"recipe_id": "R001"}（anthropic・openai）'


@check("V7 SDK ごとに違う例外が ProviderError にそろう")
async def _():
    got = {}
    for name in REAL:
        async with provider_under_test(name, fault="429") as p:
            try:
                await p.complete(TEXT_REQ)
            except ProviderError as e:
                got[f"{name} 429"] = (e.kind, e.retryable, type(e.__cause__).__name__)
        received: list = []
        async with provider_under_test(name, fault="sse-error") as p:
            try:
                async for ev in p.stream(TEXT_REQ):
                    received.append(ev)
            except ProviderError as e:
                got[f"{name} sse-error"] = (e.kind, event_shape(received), type(e.__cause__).__name__)
    eq(got, {
        "anthropic 429": ("rate_limited", True, "RateLimitError"),
        "anthropic sse-error": ("stream_error", "TextDelta×2", "APIStatusError"),
        "openai 429": ("rate_limited", True, "RateLimitError"),
        "openai sse-error": ("stream_error", "TextDelta×2", "APIError"),
    }, "kind と元の例外")
    return ("429 → rate_limited（どちらも RateLimitError）・途中の error → stream_error"
            "（anthropic は APIStatusError、openai は APIError。どちらも TextDelta×2 のあと）")


@check("V8 契約テスト（pytest）：6種類のテストを3実装に流す")
def _():
    passed = run_pytest("src/session04/test_contract.py")
    eq(passed, 18, "passed の数（6 × 3）")
    return f"{passed} passed"


@check("V9 POST /api/ask：LLM_PROVIDER だけで上流が替わり、失敗は共通エラー本文になる")
async def _():
    got = {}
    for name in REAL:
        os.environ["LLM_PROVIDER"] = name
        try:
            async with app.router.lifespan_context(app):
                async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
                    r = await c.post("/api/ask", json={"question": PROMPT})
        finally:
            os.environ.pop("LLM_PROVIDER", None)
        eq(r.status_code, 200, f"{name}：status（{r.text}）")
        body = r.json()
        got[name] = (body["provider"], body["stop_reason"], body["usage"]["input_tokens"], body["usage"]["output_tokens"])
        assert r.headers["x-request-id"].startswith("req_"), r.headers
        eq(body["request_id"], r.headers["x-request-id"], f"{name}：本文の request_id とヘッダ")
        assert "upstream_request_id" not in body, f"上流の ID が応答に出ている: {body}"
    eq(got, {"anthropic": ("anthropic", "end_turn", 34, 181), "openai": ("openai", "end_turn", 34, 181)}, "応答")

    fake = FakeProvider([ProviderError("overloaded", provider="fake", status_code=529)])
    app.dependency_overrides[get_provider] = lambda: fake
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/ask", json={"question": PROMPT})
    finally:
        app.dependency_overrides.clear()
    eq(r.status_code, 503, "Fake の失敗：status")
    err = r.json()["error"]
    eq((err["type"], err["message"]), ("upstream_unavailable", UPSTREAM_MESSAGE), "エラー本文")
    eq(err["request_id"], r.headers["x-request-id"], "request_id とヘッダ")
    return ("anthropic=200・openai=200（input_tokens=34 output_tokens=181・request_id は x-request-id と同じ）"
            "・Fake の ProviderError → 503 upstream_unavailable")


finish("session04")
