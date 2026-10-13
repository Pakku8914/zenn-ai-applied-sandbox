"""環境構築の章で動かす最小のアプリ。

- GET  /health                … 生存確認（依存先は見ない）
- GET  /health/deps           … mockllm・VOICEVOX ENGINE・Whisper のモデルのキャッシュを確認する
- POST /api/fridge/scan       … 冷蔵庫の写真（multipart の image）→ 食材リスト（構造化出力）
- POST /api/voice/loopback    … VOICEVOX で文を読み上げ、faster-whisper で聞き取り直して CER を出す（閉ループの自己診断）
"""

from __future__ import annotations

import base64
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anthropic
import anyio
import httpx2
from anthropic import AsyncAnthropic, transform_schema
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from ulid import ULID

from kondate import __version__, stt
from kondate.audio import wav_to_float32
from kondate.llm import AnthropicProvider, ChatRequest
from kondate.metrics import cer
from kondate.settings import get_settings
from kondate.tts import Voicevox
from kondate.usage import UsageLog

settings = get_settings()

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 40_000_000          # 展開すると巨大になる画像（解凍爆弾）を拒否する
LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
LOOPBACK_MAX_CHARS = 100                     # 音声合成・認識は CPU を食うので、1回に扱う長さを制限する
LOOPBACK_CER_MAX = 0.10                      # 閉ループの合格ライン（requirements.md「章に書いてよい実測値」参照）
FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"


class Ingredient(BaseModel):
    name: str
    quantity: str = Field(description="見た目の分量（例：1/2玉）")
    amount: float
    unit: str
    confidence: float = Field(ge=0, le=1)
    category: str


class FridgeScan(BaseModel):
    ingredients: list[Ingredient]


class LoopbackIn(BaseModel):
    text: str = Field(default=LOOPBACK_TEXT, min_length=1, max_length=LOOPBACK_MAX_CHARS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = AsyncAnthropic()  # 接続先とキーは環境変数 ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む
    app.state.llm = AnthropicProvider(client)
    app.state.voicevox = Voicevox()
    app.state.usage = UsageLog()
    app.state.stt_limiter = anyio.CapacityLimiter(1)  # 音声認識は CPU を使い切るので同時に1つだけ
    yield
    await client.close()
    await app.state.voicevox.aclose()


app = FastAPI(title="こんだてAI マルチモーダル", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    # 上流の生のエラー文は返さない。日本語の固定文と request_id だけを返す（①バックエンド編と同じ形）
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/health/deps")
async def health_deps(request: Request) -> JSONResponse:
    results: dict[str, str] = {}
    try:
        async with httpx2.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.mockllm_url}/_mock/health")
        results["mockllm"] = f"ok ({r.json()['version']})" if r.status_code == 200 else f"ng ({r.status_code})"
    except Exception as e:  # 疎通確認なので種類を問わず NG として返す
        results["mockllm"] = f"ng ({type(e).__name__})"
    try:
        results["voicevox"] = f"ok ({await request.app.state.voicevox.version()})"
    except Exception as e:
        results["voicevox"] = f"ng ({type(e).__name__})"
    cached = await anyio.to_thread.run_sync(stt.is_cached)
    results["whisper"] = f"ok ({settings.whisper_model}・キャッシュ済み)" if cached else f"ng ({settings.whisper_model}・未取得)"
    ok = all(v.startswith("ok") for v in results.values())
    return JSONResponse({"status": "ok" if ok else "ng", "deps": results}, status_code=200 if ok else 503)


def prepare_image(raw: bytes) -> tuple[bytes, dict]:
    """中身で形式を確かめ、向きを直し、EXIF（位置情報を含む）を捨てて JPEG に作り直す。長辺が大きければ縮小する。"""
    with Image.open(io.BytesIO(raw)) as img:
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValueError(f"unsupported:{img.format}")
        had_exif = len(img.getexif()) > 0
        img = ImageOps.exif_transpose(img).convert("RGB")
    original = img.size
    img.thumbnail((settings.image_max_long_edge, settings.image_max_long_edge))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)          # exif= を渡さないので EXIF は書き出されない
    return out.getvalue(), {
        "original_size": list(original), "sent_size": list(img.size),
        "media_type": "image/jpeg", "exif_removed": had_exif, "bytes": out.tell(),
    }


@app.post("/api/fridge/scan")
async def fridge_scan(request: Request, image: UploadFile) -> JSONResponse:
    raw = await image.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", f"画像は {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください")
    try:
        jpeg, info = await anyio.to_thread.run_sync(prepare_image, raw)
    except (UnidentifiedImageError, Image.DecompressionBombError, ValueError, OSError):
        return error(request, 415, "unsupported_media", "JPEG・PNG・WebP・GIF の画像を送ってください")

    req = ChatRequest(
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()}},
            {"type": "text", "text": FRIDGE_PROMPT},
        ]}],
        output_schema=transform_schema(FridgeScan),
        max_tokens=settings.llm_max_tokens,
    )
    try:
        result = await request.app.state.llm.complete(req)
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", "画像の読み取りに失敗しました。時間をおいて試してください")
    try:
        scan = FridgeScan.model_validate_json(result.text)
    except ValidationError:
        return error(request, 502, "invalid_output", "読み取り結果の形式が正しくありませんでした")

    request.app.state.usage.add("u001", "llm", settings.llm_model, input_tokens=result.usage.input_tokens,
                                output_tokens=result.usage.output_tokens, request_id=result.request_id)
    return JSONResponse({
        "ingredients": [i.model_dump() for i in scan.ingredients],
        "image": info,
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
    })


@app.post("/api/voice/loopback")
async def voice_loopback(request: Request, body: LoopbackIn | None = None) -> JSONResponse:
    body = body or LoopbackIn()
    vv: Voicevox = request.app.state.voicevox
    try:
        await vv.ensure_user_dict()
        tts = await vv.synthesize(body.text, sample_rate=settings.stt_sample_rate)
    except httpx2.HTTPError:
        return error(request, 503, "tts_unavailable", "音声合成エンジンに接続できませんでした")
    audio, rate = wav_to_float32(tts.wav)
    res = await anyio.to_thread.run_sync(stt.transcribe, audio, rate, limiter=request.app.state.stt_limiter)
    score = round(cer(body.text, res.text), 4)
    usage = request.app.state.usage
    usage.add("u001", "tts", f"voicevox:{vv.speaker}", audio_seconds=round(tts.audio_seconds, 3), processing_seconds=round(tts.processing_seconds, 3))
    usage.add("u001", "stt", f"whisper:{settings.whisper_model}", audio_seconds=round(res.audio_seconds, 3), processing_seconds=round(res.processing_seconds, 3))
    return JSONResponse({
        "text": body.text,
        "kana": tts.kana,
        "transcript": res.text,
        "cer": score,
        "passed": score <= LOOPBACK_CER_MAX,
        "tts": {"audio_seconds": round(tts.audio_seconds, 2), "processing_seconds": round(tts.processing_seconds, 2), "rtf": round(tts.rtf, 2)},
        "stt": {"model": settings.whisper_model, "processing_seconds": round(res.processing_seconds, 2), "rtf": round(res.rtf, 2)},
        "credit": settings.voicevox_credit,
    })
