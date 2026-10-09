"""セッション3（LLM 呼び出しを API にする）の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session03

アプリは httpx2.ASGITransport で同じプロセスに載せ、lifespan も自分で回す（api の APP_MODULE に依存しない）。
接続先とキーは明示的に mockllm に向けるので、.env で実 API に向けていても課金されない。
"""

from __future__ import annotations

import importlib.util
import os

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from pydantic import ValidationError

import src.session03.app as app_module
from kondate.verifykit import check, eq, finish
from src.session03.app import QUICK_TIMEOUT, create_app
from src.session03.config import LLMSettings
from src.session03.harness import (BASE, QUESTION, REQ_ID, assert_error, capture_logs, mock_settings,
                                   mock_stats, reset_mock, running)

LOGS = capture_logs()


@check("V1 設定は環境変数から読み、キーは伏せ字・未設定なら起動前に失敗")
def _():
    saved = dict(os.environ)
    try:
        os.environ.update({
            "ANTHROPIC_API_KEY": "sk-test-secret", "ANTHROPIC_BASE_URL": "http://mockllm:8080",
            "LLM_MODEL": "model-from-env", "LLM_TIMEOUT_SECONDS": "12.5",
        })
        s = LLMSettings()
        eq((s.llm_model, s.llm_timeout_seconds, s.llm_connect_timeout_seconds, s.llm_max_retries),
           ("model-from-env", 12.5, 5.0, 0), "環境変数から読んだ値と既定値")
        eq(s.anthropic_api_key.get_secret_value(), "sk-test-secret", "キーの中身")
        for shown in (repr(s), str(s.model_dump())):
            assert "sk-test-secret" not in shown, f"キーが表示に出ている: {shown}"
        eq(s.forwards_mock_headers, True, "接続先が mockllm なら x-mock-* を渡す")
        real = LLMSettings(anthropic_base_url="https://api.anthropic.com")
        eq(real.forwards_mock_headers, False, "接続先が本物なら x-mock-* を渡さない")
        del os.environ["ANTHROPIC_API_KEY"]
        try:
            LLMSettings()
        except ValidationError as e:
            eq([err["loc"] for err in e.errors()], [("anthropic_api_key",)], "足りない項目")
        else:
            raise AssertionError("キーが無いのに設定が作れてしまった")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return "LLM_MODEL・LLM_TIMEOUT_SECONDS を読む／キーは SecretStr／未設定は ValidationError"


@check("V2 クライアントは lifespan で1つ・終了時に閉じる")
async def _():
    created: list[AsyncAnthropic] = []
    original = app_module.make_client

    def counting(settings: LLMSettings) -> AsyncAnthropic:
        created.append(original(settings))
        return created[-1]

    app_module.make_client = counting
    try:
        app = create_app(mock_settings())
        async with running(app) as client:
            for _ in range(3):
                (await client.post("/api/ask", json={"question": QUESTION})).raise_for_status()
            llm = app.state.llm
            eq(llm.is_closed(), False, "lifespan の途中")
            quick = llm.with_options(timeout=QUICK_TIMEOUT)
            assert quick is not llm and quick._client is llm._client, "with_options が別の接続プールを作った"
            eq((quick.timeout.read, quick.timeout.connect, llm.timeout.read, llm.timeout.connect),
               (2.0, 1.0, 30.0, 5.0), "with_options は元のクライアントの設定を変えない")
    finally:
        app_module.make_client = original
    eq(len(created), 1, "3リクエストで作られたクライアントの数")
    eq(llm.is_closed(), True, "lifespan の終了後")

    # 落とし穴：with_options のコピーを async with で閉じると、共有している元のプールも閉じる
    base = AsyncAnthropic(api_key="mock-key", base_url=BASE.mockllm_url)
    async with base.with_options(timeout=QUICK_TIMEOUT):
        pass
    eq(base.is_closed(), True, "コピーを閉じたあとの元のクライアント")
    return "3リクエストで生成1回・終了後 is_closed=True・with_options はプール共有（コピーを閉じると元も閉じる）"


@check("V3 POST /api/ask が回答・usage・request_id を返す")
async def _():
    await reset_mock()
    LOGS.lines.clear()
    app = create_app(mock_settings())
    async with running(app) as client:
        r = await client.post("/api/ask", json={"question": QUESTION})
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    eq(list(body), ["answer", "stop_reason", "usage", "request_id"], "キーと順序")
    assert body["answer"].startswith("鶏むね肉とキャベツがあるなら"), body["answer"][:30]
    eq(body["usage"], {"input_tokens": 34, "output_tokens": 181,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "usage")
    eq(body["stop_reason"], "end_turn", "stop_reason")
    assert REQ_ID.match(body["request_id"]), body["request_id"]
    eq(r.headers["x-request-id"], body["request_id"], "x-request-id ヘッダと本文の request_id")
    assert "req_mock_" not in r.text, "上流の request-id はクライアントに返さない"
    eq(LOGS.lines, [f"llm_call ok request_id={body['request_id']} upstream_request_id=req_mock_000001"
                    " input_tokens=34 output_tokens=181 stop_reason=end_turn"], "ログ")
    return (f"200・{len(body['answer'])} 字・input_tokens=34 output_tokens=181・end_turn"
            "・ログに upstream_request_id=req_mock_000001")


@check("V4 空の question は 422 invalid_request")
async def _():
    app = create_app(mock_settings())
    async with running(app) as client:
        r = await client.post("/api/ask", json={"question": ""})
    assert_error(r, 422, "invalid_request")
    eq(r.json()["error"]["message"], "入力値が正しくありません：question", "422 の message")
    return "入力値が正しくありません：question"


@check("V5 TTFT 2.5 秒：/api/ask は 200・/api/ask/quick は 504 upstream_timeout")
async def _():
    app = create_app(mock_settings())
    slow = {"x-mock-ttft-ms": "2500"}
    async with running(app) as client:
        normal = await client.post("/api/ask", json={"question": QUESTION}, headers=slow)
        quick = await client.post("/api/ask/quick", json={"question": QUESTION}, headers=slow)
    eq(normal.status_code, 200, f"/api/ask（本文 {normal.text}）")
    assert_error(quick, 504, "upstream_timeout")


@check("V6 上流の失敗を翻訳し、上流の文を漏らさない")
async def _():
    await reset_mock()
    LOGS.lines.clear()
    app = create_app(mock_settings())
    async with running(app) as client:
        async def ask(headers: dict[str, str]) -> httpx2.Response:
            return await client.post("/api/ask", json={"question": QUESTION}, headers=headers)

        limited = await ask({"x-mock-fault": "429"})
        assert_error(limited, 429, "rate_limited")
        eq(limited.headers.get("retry-after"), "1", "retry-after")
        assert_error(await ask({"x-mock-fault": "500"}), 503, "upstream_unavailable")
        assert_error(await ask({"x-mock-fault": "529"}), 503, "upstream_unavailable")
        assert_error(await ask({"x-mock-scenario": "no_such_scenario"}), 502, "upstream_error")
    down = create_app(mock_settings(anthropic_base_url="http://mockllm:9"))  # 誰も待ち受けていないポート
    async with running(down) as client:
        assert_error(await client.post("/api/ask", json={"question": QUESTION}), 503, "upstream_unavailable")

    stats = await mock_stats()
    eq(stats["by_status"], {"429": 1, "500": 1, "529": 1, "400": 1}, "mockllm が受けた回数（max_retries=0 なので各1回）")
    eq(len(LOGS.lines), 5, "失敗のログの行数")
    assert all(line.startswith("llm_call failed ") for line in LOGS.lines), LOGS.lines
    for i, status in enumerate(["429", "500", "529", "400"], start=1):
        line = LOGS.lines[i - 1]
        assert f"upstream_request_id=req_mock_{i:06d} " in line and line.endswith(f"status={status}"), line
    assert "upstream_request_id=- error=APIConnectionError status=-" in LOGS.lines[4], LOGS.lines[4]
    return "429→429（retry-after: 1）・500/529/接続失敗→503・400→502・上流は各1回"


@check("V7 anthropic 1.x の差")
async def _():
    llm = AsyncAnthropic(api_key="mock-key", base_url=BASE.mockllm_url)
    try:
        try:
            await llm.messages.create(model=BASE.llm_model, max_tokens=16, temperature=0.2,  # type: ignore[call-arg]
                                      messages=[{"role": "user", "content": QUESTION}])
        except TypeError as e:
            assert "temperature" in str(e), str(e)
        else:
            raise AssertionError("temperature を受け付けた")
        eq((llm.timeout.read, llm.timeout.connect, llm.max_retries), (600.0, 5.0, 2), "SDK の既定値")
    finally:
        await llm.close()
    assert anthropic.Timeout is httpx2.Timeout, anthropic.Timeout
    eq(importlib.util.find_spec("httpx"), None, "httpx（0.x 系の HTTP 層）")
    return "temperature は TypeError・Timeout は httpx2・既定 600秒/5秒/2回・httpx なし"


finish("session03")
