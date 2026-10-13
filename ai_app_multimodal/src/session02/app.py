"""セッション2：アップロードの受付（POST /api/uploads）。

画像（JPEG・PNG・WebP・GIF）か PDF を受け取り、中身で形式を確かめてから out/uploads/ に保存する。
ファイル名と Content-Type（送り手の自己申告）は、形式の判定にも保存先の名前にも使わない。

起動：APP_MODULE=src.session02.app:app docker compose up -d --wait api
"""

from __future__ import annotations

import hashlib
import io
import warnings
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from PIL import Image
from pypdf import PdfReader
from ulid import ULID

from kondate import __version__
from kondate.settings import get_settings

settings = get_settings()

# ---- 本書全体で固定する受付の値（後の章も同じ値を使う） ----
Image.MAX_IMAGE_PIXELS = 40_000_000
# Pillow は上限の2倍までは「警告」しか出さない。警告を例外に格上げして、上限ちょうどで止める
warnings.simplefilter("error", Image.DecompressionBombWarning)
MAX_PDF_PAGES = 200
UPLOAD_DIR = Path("out/uploads")

IMAGE_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
]

MSG_TOO_LARGE = f"ファイルは {settings.upload_max_bytes // (1024 * 1024)}MB 以下にしてください"
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"


class Rejected(Exception):
    """受け付けられないファイル。status・type・message は利用者にそのまま返す固定の値。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def unsupported() -> Rejected:
    return Rejected(415, "unsupported_media", MSG_UNSUPPORTED)


def sniff(raw: bytes) -> str | None:
    """先頭のバイト（マジックバイト）から形式の候補を返す。あくまで候補で、確定ではない。"""
    for magic, fmt in MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":  # WebP は RIFF という入れ物の 8 バイト目（先頭を0バイト目として）に印がある
        return "WEBP"
    return None


def check_image(raw: bytes, fmt: str) -> str:
    """候補の形式として Pillow で開けるか（ヘッダーまで）と画素数を確かめ、拡張子を返す。画素の展開はしない。"""
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:  # 候補の形式のデコーダーだけを試す
            return IMAGE_EXT[img.format]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):  # UnidentifiedImageError は OSError の仲間
        raise unsupported() from None


def check_pdf(raw: bytes) -> str:
    """pypdf で開けるかとページ数を確かめる。"""
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れた PDF に pypdf はさまざまな例外を投げる。種類を問わず「開けない」と扱う
        raise unsupported() from None
    if pages == 0:
        raise unsupported()
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    return "pdf"


def inspect_upload(raw: bytes) -> tuple[str, str]:
    """中身だけを見て (kind, 拡張子) を決める。"""
    fmt = sniff(raw)
    if fmt is None:
        raise unsupported()
    if fmt == "PDF":
        return "pdf", check_pdf(raw)
    return "image", check_image(raw, fmt)


def save_upload(dest: Path, upload_id: str, ext: str, raw: bytes) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / f"{upload_id}.{ext}").open("xb") as f:  # "x"：同じ名前があれば上書きせずに失敗する
        f.write(raw)


def upload_dir() -> Path:
    """保存先。verify では dependency_overrides で差し替える。"""
    return UPLOAD_DIR


app = FastAPI(title="こんだてAI セッション2：アップロードの受付", version=__version__)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = f"req_{ULID()}"
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def error(request: Request, status: int, type_: str, message: str) -> JSONResponse:
    # 上流（Pillow・pypdf）の生のエラー文は返さない。日本語の固定文と request_id だけを返す（①と同じ形）
    return JSONResponse(
        {"error": {"type": type_, "message": message, "request_id": request.state.request_id}},
        status_code=status,
    )


async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    names = dict.fromkeys(str(e["loc"][-1]) for e in exc.errors())  # 重複を除き、順序は保つ
    return error(request, 422, "invalid_request", f"入力値が正しくありません：{'、'.join(names)}")


app.add_exception_handler(RequestValidationError, on_validation_error)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/uploads")
async def create_upload(
    request: Request,
    file: UploadFile,
    dest: Annotated[Path, Depends(upload_dir)],
) -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)  # 上限より1バイトだけ多く読む
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    try:
        kind, ext = await anyio.to_thread.run_sync(inspect_upload, raw)  # Pillow・pypdf は同期処理
    except Rejected as e:
        return error(request, e.status, e.type, e.message)

    upload_id = f"up_{ULID()}"  # 保存名はサーバーが採番する。利用者のファイル名は使わない
    await anyio.to_thread.run_sync(save_upload, dest, upload_id, ext, raw)
    return JSONResponse(
        {"upload_id": upload_id, "kind": kind, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        status_code=201,
    )
