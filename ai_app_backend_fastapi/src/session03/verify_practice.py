"""セッション3の練習問題の解答（src/session03/exercises/）の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session03
"""

from __future__ import annotations

import importlib.util
import os

import anthropic
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from kondate.verifykit import check, eq, finish
from src.session03.errors import ApiError, translate
from src.session03.exercises import q2_lifespan, q6_quick
from src.session03.exercises.q1_settings import QuickSettings
from src.session03.exercises.q3_cases import collect_errors
from src.session03.exercises.q5_logging import ask_logged, kv
from src.session03.exercises.q7_deadline import ask_with_deadline
from src.session03.harness import (BASE, QUESTION, assert_error, capture_logs, mock_settings, mock_stats,
                                   reset_mock, running)
from src.session03.llm import make_client

LOGS = capture_logs()
MOCK = {"anthropic_api_key": "mock-key", "anthropic_base_url": BASE.mockllm_url, "llm_model": BASE.llm_model}


@check("Q1 LLM_QUICK_TIMEOUT_SECONDS を設定に足す（既定 2.0・0 以下は ValidationError）")
def _():
    saved = dict(os.environ)
    try:
        os.environ.pop("LLM_QUICK_TIMEOUT_SECONDS", None)
        eq(QuickSettings(**MOCK).llm_quick_timeout_seconds, 2.0, "既定値")
        os.environ["LLM_QUICK_TIMEOUT_SECONDS"] = "1.5"
        eq(QuickSettings(**MOCK).llm_quick_timeout_seconds, 1.5, "環境変数から読んだ値")
        os.environ["LLM_QUICK_TIMEOUT_SECONDS"] = "0"
        try:
            QuickSettings(**MOCK)
        except ValidationError as e:
            eq([(err["loc"], err["type"]) for err in e.errors()],
               [(("llm_quick_timeout_seconds",), "greater_than")], "検証エラー")
        else:
            raise AssertionError("0 秒を受け付けた")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return "既定 2.0・環境変数 1.5 を読む・0 は greater_than"


@check("Q2 lifespan で1つだけ作る：3リクエストで生成1回・終了後に閉じる")
async def _():
    settings = mock_settings()
    created: list[AsyncAnthropic] = []

    def make_llm() -> AsyncAnthropic:
        created.append(make_client(settings))
        return created[-1]

    app = q2_lifespan.create_app(make_llm, settings)
    async with running(app) as client:
        for _ in range(3):
            r = await client.post("/api/ask", json={"question": QUESTION})
            eq(r.status_code, 200, f"status（本文 {r.text}）")
    eq(len(created), 1, "作られたクライアントの数")
    eq(created[0].is_closed(), True, "lifespan の終了後")
    return "生成 1 回・200 が 3 回・終了後 is_closed=True"


def translate_wrong_order(exc: anthropic.APIError) -> ApiError:
    """問題文に載せた、判定の順序を誤った翻訳関数。"""
    if isinstance(exc, anthropic.APIConnectionError):
        return ApiError(503, "upstream_unavailable")
    if isinstance(exc, anthropic.APITimeoutError):
        return ApiError(504, "upstream_timeout")
    if isinstance(exc, anthropic.APIStatusError):
        return ApiError(503, "upstream_unavailable") if exc.status_code >= 500 else ApiError(502, "upstream_error")
    if isinstance(exc, anthropic.RateLimitError):
        return ApiError(429, "rate_limited")
    return ApiError(502, "upstream_error")


@check("Q3 実際の例外で翻訳関数を確かめる（判定は子クラスから）")
async def _():
    errors = await collect_errors(BASE.mockllm_url, BASE.llm_model)
    eq(sorted(errors), ["400", "429", "500", "529", "connect", "timeout"], "集めた例外")
    eq(type(errors["timeout"]).__name__, "APITimeoutError", "時間切れの例外")
    assert isinstance(errors["timeout"], anthropic.APIConnectionError), "APITimeoutError は APIConnectionError の子"
    assert isinstance(errors["429"], anthropic.APIStatusError), "RateLimitError は APIStatusError の子"
    right = {k: (translate(e).status_code, translate(e).type) for k, e in errors.items()}
    eq(right, {"429": (429, "rate_limited"), "500": (503, "upstream_unavailable"),
               "529": (503, "upstream_unavailable"), "400": (502, "upstream_error"),
               "timeout": (504, "upstream_timeout"), "connect": (503, "upstream_unavailable")}, "正しい順の翻訳")
    wrong = {k: translate_wrong_order(e).type for k, e in errors.items()}
    eq((wrong["timeout"], wrong["429"]), ("upstream_unavailable", "upstream_error"), "誤った順の翻訳")
    return "正しい順：timeout→504・429→429／誤った順：timeout→503 upstream_unavailable・429→502 upstream_error"


@check("Q4 0.x の記事のコードはこの環境で止まる（httpx が無い・temperature が TypeError）")
def _():
    eq(importlib.util.find_spec("httpx"), None, "import httpx")
    client = anthropic.Anthropic(api_key="mock-key", base_url=BASE.mockllm_url)
    try:
        try:
            client.messages.create(model=BASE.llm_model, max_tokens=16, temperature=0.7,  # type: ignore[call-arg]
                                   messages=[{"role": "user", "content": QUESTION}])
        except TypeError as e:
            assert "temperature" in str(e), str(e)
        else:
            raise AssertionError("temperature を受け付けた")
    finally:
        client.close()
    return "ModuleNotFoundError（httpx）・TypeError（temperature）"


@check("Q5 成功・失敗の両方で key=value の1行を残し、質問文とキーは残さない")
async def _():
    eq(kv(a="x y", b=None, c=3, d='say "hi"'), 'a="x y" b=- c=3 d="say \\"hi\\""', "kv の引用")
    await reset_mock()
    LOGS.lines.clear()
    settings = mock_settings()
    llm = make_client(settings)
    try:
        await ask_logged(llm, settings, QUESTION, request_id="req_q5_ok")
        try:
            await ask_logged(llm, settings, QUESTION, request_id="req_q5_ng", extra_headers={"x-mock-fault": "500"})
        except ApiError as e:
            eq((e.status_code, e.type), (503, "upstream_unavailable"), "翻訳")
            cause = type(e.__cause__).__name__
        else:
            raise AssertionError("500 なのに成功した")
    finally:
        await llm.close()
    head = f"event=llm_call request_id=%s model={BASE.llm_model} question_chars={len(QUESTION)}"
    eq(LOGS.lines, [
        head % "req_q5_ok" + " outcome=ok upstream_request_id=req_mock_000001 stop_reason=end_turn"
                             " input_tokens=34 output_tokens=181",
        head % "req_q5_ng" + f" outcome=error error={cause} status=500 upstream_request_id=req_mock_000002",
    ], "ログ")
    for line in LOGS.lines:
        assert QUESTION not in line and "mock-key" not in line, line
    return f"ok と error の2行・question_chars={len(QUESTION)}・質問文とキーは含まない"


@check("Q6 quick のタイムアウトを設定から作る（1.0 秒：TTFT 1.5 秒は 504・0.5 秒は 200）")
async def _():
    settings = QuickSettings(**MOCK, llm_quick_timeout_seconds=1.0)
    eq((q6_quick.quick_timeout(settings).read, q6_quick.quick_timeout(settings).connect), (1.0, 1.0),
       "connect は全体より長くしない")
    app = q6_quick.create_app(settings)
    async with running(app) as client:
        def post(path: str, ttft: str):
            return client.post(path, json={"question": QUESTION}, headers={"x-mock-ttft-ms": ttft})

        eq((await post("/api/ask", "1500")).status_code, 200, "/api/ask（30 秒）")
        assert_error(await post("/api/ask/quick", "1500"), 504, "upstream_timeout")
        eq((await post("/api/ask/quick", "500")).status_code, 200, "/api/ask/quick（TTFT 0.5 秒）")
        quick = app.state.llm_quick
    eq(quick.is_closed(), True, "元を閉じるとコピーも閉じている（同じ接続プール）")
    return "/api/ask=200・quick(1.5秒)=504・quick(0.5秒)=200・コピーは元と同じプール"


@check("Q7 リトライ込みの締め切り：締め切りなしは3回目で成功・1.0 秒の締め切りは2回目の途中で 504")
async def _():
    await reset_mock()
    LOGS.lines.clear()
    settings = mock_settings(llm_max_retries=2)
    llm = make_client(settings)
    fault = {"x-mock-fault": "500", "x-mock-fault-times": "2"}
    try:
        answer = await ask_with_deadline(llm, settings, QUESTION, request_id="req_q7_a", deadline_s=10.0,
                                         extra_headers={**fault, "x-mock-fault-key": "s03-q7-a"})
        eq(answer.stop_reason, "end_turn", "締め切りなしの結果")
        try:
            await ask_with_deadline(llm, settings, QUESTION, request_id="req_q7_b", deadline_s=1.0,
                                    extra_headers={**fault, "x-mock-fault-key": "s03-q7-b"})
        except ApiError as e:
            eq((e.status_code, e.type), (504, "upstream_timeout"), "締め切り切れの翻訳")
        else:
            raise AssertionError("締め切りを過ぎても成功した")
    finally:
        await llm.close()
    faults = (await mock_stats())["faults"]
    eq((faults["s03-q7-a"]["calls"], faults["s03-q7-b"]["calls"]), (3, 2), "mockllm が受けた回数")
    eq(LOGS.lines[-1], "llm_call deadline_exceeded request_id=req_q7_b deadline_s=1.0", "締め切りのログ")
    return "締め切りなし：3回目で 200・締め切り 1.0 秒：2回呼んだところで 504 upstream_timeout"


finish("session03-practice")
