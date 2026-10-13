"""セッション4：冷蔵庫の写真から食材リスト（POST /api/fridge/scan）。

multipart の image を受け付け、受付検査と前処理（セッション2・3）→ 構造化出力 → Pydantic で再検証 → 要確認の印付け。
応答：{ingredients:[{name, quantity, amount, unit, confidence, category}], needs_review, issues:[…], image:{…}, usage}

起動：APP_MODULE=src.session04.app:app docker compose up -d --wait api
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import anyio
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ulid import ULID

from kondate import __version__
from kondate.llm import AnthropicProvider, LLMProvider
from kondate.settings import get_settings
from src.session04.intake import MSG_TOO_LARGE, Rejected, accept_image
from src.session04.review import find_issues
from src.session04.scan import InvalidOutput, UpstreamUnavailable, scan_fridge

settings = get_settings()
MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_UPSTREAM = "画像の読み取りに失敗しました。時間をおいて試してください"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    yield
    await client.close()


app = FastAPI(title="こんだてAI セッション4：冷蔵庫の写真から食材リスト", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    # 上流の生のエラー文は返さない。日本語の固定文と request_id だけを返す
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


app.add_exception_handler(RequestValidationError, on_validation_error)


def get_llm(request: Request) -> LLMProvider:
    """使う LLM。verify では dependency_overrides で FakeProvider などに差し替える。"""
    return request.app.state.llm


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/fridge/scan")
async def fridge_scan(
    request: Request,
    image: UploadFile,
    llm: Annotated[LLMProvider, Depends(get_llm)],
) -> JSONResponse:
    raw = await image.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        prepared = await anyio.to_thread.run_sync(accept_image, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    try:
        result = await scan_fridge(llm, prepared.data)
    except UpstreamUnavailable:
        return error(request, 503, "upstream_unavailable", MSG_UPSTREAM)
    except InvalidOutput:
        return error(request, 502, "invalid_output", MSG_INVALID_OUTPUT)

    issues = find_issues(result.scan.ingredients)
    return JSONResponse({
        "ingredients": [i.model_dump() for i in result.scan.ingredients],
        "needs_review": bool(issues),
        "issues": issues,
        "image": prepared.info(),
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
    })
