"""復習1（S02〜S04）の解答の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review01

アプリは httpx2.ASGITransport で同じプロセスに載せ、lifespan も自分で回す（api の APP_MODULE に依存しない）。
本物の SDK は明示的に mockllm に向けるので課金されない。問題2（コードレビュー）は読解問題なので検査しない。
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx2
from fastapi import FastAPI

from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.review01.app import ProviderFactory, create_app
from src.review01.errors import MESSAGES, from_provider_error
from src.review01.providers import (ChatRequest, FakeItem, FakeProvider, ProviderError, open_provider,
                                    retry_after_seconds, translate_error)

ROOT = Path(__file__).resolve().parents[2]
BASE = get_settings()
REQ_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")
SUGGEST = {"recipe_id": "R001", "question": "この料理に合う副菜を教えて"}
DEFAULT_ANSWER = ("（mockllm の既定応答）「この料理に合う副菜を教えて」についてですね。"
                  "冷蔵庫にある食材と、調理にかけられる時間を教えていただければ、献立を提案します。")

# 500 の検査で出るトレースバックや警告のログを、検証の出力に混ぜない
logging.getLogger("kondate.review01").addHandler(logging.NullHandler())


def mock_llm(name: str = "anthropic", headers: dict[str, str] | None = None, *,
             base_url: str | None = None, timeout: float = 10.0) -> ProviderFactory:
    url = base_url or (BASE.mockllm_url if name == "anthropic" else f"{BASE.mockllm_url}/v1")
    return lambda: open_provider(name, model=BASE.llm_model, base_url=url, api_key="mock-key",
                                 max_retries=0, timeout=timeout, default_headers=headers)


def fake_llm(*scripts: list[FakeItem]) -> ProviderFactory:
    @asynccontextmanager
    async def open_fake() -> AsyncIterator[FakeProvider]:
        yield FakeProvider(*scripts)

    return open_fake


@asynccontextmanager
async def serve(open_llm: ProviderFactory) -> AsyncIterator[tuple[FastAPI, httpx2.AsyncClient]]:
    app = create_app(open_llm)
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
            yield app, client


def error_of(r: httpx2.Response) -> tuple[int, str]:
    """共通エラー本文の形・request_id・上流の文が漏れていないことを確かめ、(status, type) を返す。"""
    err = r.json()["error"]
    eq(sorted(err), ["message", "request_id", "type"], f"error のキー（{r.text}）")
    assert REQ_ID.match(err["request_id"]), err["request_id"]
    eq(r.headers["x-request-id"], err["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "mockllm" not in r.text and "req_mock_" not in r.text, f"上流の文が漏れている: {r.text}"
    return r.status_code, err["type"]


@check("R1 問題1：エラー対応表の10行が、組み立てたアプリの応答と一致する")
async def _():
    rows: list[tuple[int, str]] = []
    async with serve(mock_llm()) as (_, c):
        rows.append(error_of(await c.get("/api/recipes/R1")))
        rows.append(error_of(await c.get("/api/recipes/R999")))
        not_allowed = await c.delete("/api/recipes/R001")
        rows.append(error_of(not_allowed))
        assert "GET" in not_allowed.headers.get("allow", ""), not_allowed.headers
        extra = await c.post("/api/suggest", json={**SUGGEST, "temperature": 0.2})
        rows.append(error_of(extra))
        eq(extra.json()["error"]["message"], "入力値が正しくありません：temperature", "422 の message")
    upstream = [
        mock_llm(headers={"x-mock-fault": "429"}),
        mock_llm(headers={"x-mock-fault": "529"}),
        mock_llm(headers={"x-mock-ttft-ms": "2500"}, timeout=1.0),
        mock_llm(base_url="http://mockllm:9"),  # 誰も待ち受けていないポート
        mock_llm(headers={"x-mock-scenario": "no_such_scenario"}),
        fake_llm([RuntimeError("DB に接続できません password=kondate")]),
    ]
    for open_llm in upstream:
        async with serve(open_llm) as (_, c):
            r = await c.post("/api/suggest", json=SUGGEST)
        rows.append(error_of(r))
        if r.status_code == 429:
            eq(r.headers.get("retry-after"), "1", "429 の retry-after")
        if r.status_code == 500:
            assert "password" not in r.text, r.text
            eq(r.json()["error"]["message"], "サーバー内部でエラーが発生しました", "500 の message")
    eq(rows, [(422, "invalid_request"), (404, "not_found"), (405, "invalid_request"), (422, "invalid_request"),
              (429, "rate_limited"), (503, "upstream_unavailable"), (504, "upstream_timeout"),
              (503, "upstream_unavailable"), (502, "upstream_error"), (500, "internal_error")], "10行")
    return "422・404・405・422・429（retry-after: 1）・503・504・503・502・500"


@check("R3 問題3：retry-after を差し替え層で読み、どちらの SDK でも ProviderError.retry_after にそろう")
async def _():
    req = ChatRequest(messages=[{"role": "user", "content": SUGGEST["question"]}])
    got: dict[str, tuple[str, int | None]] = {}
    for name in ["anthropic", "openai"]:
        for seconds in [None, "30"]:
            headers = {"x-mock-fault": "429"} | ({"x-mock-retry-after": seconds} if seconds else {})
            async with mock_llm(name, headers)() as p:
                try:
                    await p.complete(req)
                except ProviderError as e:
                    got[f"{name}/{seconds or '既定'}"] = (e.kind, e.retry_after)
                else:
                    raise AssertionError(f"{name}: 429 なのに成功した")
    eq(got, {"anthropic/既定": ("rate_limited", 1), "anthropic/30": ("rate_limited", 30),
             "openai/既定": ("rate_limited", 1), "openai/30": ("rate_limited", 30)}, "kind と retry_after")
    http_date = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "Fri, 02 Oct 2026 09:00:00 GMT"}))
    eq(retry_after_seconds(http_date), None, "日時の形式の retry-after")  # type: ignore[arg-type]
    eq(retry_after_seconds(RuntimeError("応答なし")), None, "応答を持たない例外")
    eq(translate_error("fake", RuntimeError("x")).retry_after, None, "429 以外は None")
    return "anthropic・openai とも 既定→1・x-mock-retry-after: 30→30／日時の形式と応答なしは None"


@check("R4 問題4：ProviderError.kind を API のエラーへ写す表")
def _():
    kinds = ["rate_limited", "timeout", "connection", "overloaded", "server_error", "auth", "bad_request",
             "bad_response", "unsupported", "stream_error"]
    got = {}
    for kind in kinds:
        api = from_provider_error(ProviderError(kind, provider="openai", status_code=None))
        got[kind] = (api.status_code, api.type, api.headers.get("retry-after"))
        eq(api.message, MESSAGES[api.type], f"{kind} の message は固定文")
    eq(got, {
        "rate_limited": (429, "rate_limited", "5"), "timeout": (504, "upstream_timeout", None),
        "connection": (503, "upstream_unavailable", None), "overloaded": (503, "upstream_unavailable", None),
        "server_error": (503, "upstream_unavailable", None), "auth": (502, "upstream_error", None),
        "bad_request": (502, "upstream_error", None), "bad_response": (502, "upstream_error", None),
        "unsupported": (500, "internal_error", None), "stream_error": (502, "upstream_error", None),
    }, "写像")
    with_hint = from_provider_error(ProviderError("rate_limited", provider="anthropic", retry_after=12))
    eq(with_hint.headers, {"retry-after": "12"}, "上流が示した秒数を使う")
    return "10 種類の kind → 429/504/503×3/502×3/500/502（表に無い stream_error は 502）・retry-after は既定 5"


@check("R5 問題5：POST /api/suggest が LLM_PROVIDER に関係なく同じ形で答え、終了時にクライアントを閉じる")
async def _():
    outputs: dict[str, int] = {}
    for name in ["anthropic", "openai"]:
        async with serve(mock_llm(name)) as (app, c):
            health = await c.get("/health")
            recipe = await c.get("/api/recipes/R001")
            r = await c.post("/api/suggest", json=SUGGEST)
            provider = app.state.provider
        eq(health.json(), {"status": "ok", "recipes": 120}, "/health")
        eq(recipe.json(), {"id": "R001", "name": "鶏むね肉とキャベツの塩炒め", "minutes": 15}, "レシピは3項目だけ")
        eq(r.status_code, 200, f"{name} の status（本文 {r.text}）")
        body = r.json()
        eq(list(body), ["answer", "stop_reason", "provider", "usage", "request_id"], "キーと順序")
        eq((body["answer"], body["stop_reason"], body["provider"]), (DEFAULT_ANSWER, "end_turn", name), name)
        assert REQ_ID.match(body["request_id"]) and body["request_id"] == r.headers["x-request-id"], body
        assert "req_mock_" not in r.text, "上流のリクエスト ID はクライアントに返さない"
        assert body["usage"]["input_tokens"] > 0, body["usage"]
        outputs[name] = body["usage"]["output_tokens"]
        eq(provider._client.is_closed(), True, f"{name}：lifespan の終了後")
    eq(outputs["anthropic"], outputs["openai"], "output_tokens（同じ既定応答）")
    return "anthropic・openai とも 200・同じ既定応答・end_turn・output_tokens 一致／R001 は3項目／終了後 is_closed=True"


def run_pytest(path: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", path, "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    eq(r.returncode, 0, f"pytest の終了コード\n{r.stdout[-3000:]}{r.stderr[-2000:]}")
    m = re.search(r"(\d+) passed", lines[-1] if lines else "")
    assert m, lines[-1:]
    return int(m.group(1))


@check("R6 問題6：dependency_overrides で偽物のデータと FakeProvider を差し込む単体テスト（pytest）")
def _():
    passed = run_pytest("src/review01/test_suggest_fake.py")
    eq(passed, 5, "passed の数")
    return f"{passed} passed"


@check("R7 問題7：上流の失敗の HTTP 応答が3実装でそろう契約テスト（pytest）")
def _():
    passed = run_pytest("src/review01/test_error_contract.py")
    eq(passed, 15, "passed の数")
    return f"{passed} passed（3実装 × 429・529・500・timeout・bad_request）"


finish("review01")
