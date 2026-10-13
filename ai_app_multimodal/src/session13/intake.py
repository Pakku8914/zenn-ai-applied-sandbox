"""アップロードの受付検査（セッション2の app.py からコピー）。中身だけを見て形式を決め、ファイル名は使わない。"""

from __future__ import annotations

import io
import warnings
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from kondate.settings import get_settings

settings = get_settings()

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)
MAX_PDF_PAGES = 200

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
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


def check_image(raw: bytes, fmt: str) -> str:
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            return IMAGE_EXT[img.format]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise unsupported() from None


def check_pdf(raw: bytes) -> str:
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:
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


def save_upload(dest: Path, upload_id: str, ext: str, raw: bytes) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{upload_id}.{ext}"
    with path.open("xb") as f:  # "x"：同じ名前があれば上書きせずに失敗する
        f.write(raw)
    return path
