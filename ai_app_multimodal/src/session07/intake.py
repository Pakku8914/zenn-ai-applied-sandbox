"""受付検査と前処理（セッション2・3のコードを、レシート用にまとめてコピーしたもの）。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。
- 形式は中身（マジックバイト → Pillow・pypdf で開けるか）で決める。名前と Content-Type は見ない（セッション2）
- 画像は向きを直し、長辺を上限まで縮め、EXIF を捨てた JPEG に作り直す（セッション3）
- PDF はそのまま送る。あわせて pypdf で文字を先に抜き出しておく（本章）
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field

from PIL import Image, ImageOps
from pypdf import PdfReader

from kondate.settings import get_settings
from src.session07.pdftext import extract_text

settings = get_settings()

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める（セッション2）
MAX_PDF_PAGES = 200

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
    for magic, fmt in MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


@dataclass(frozen=True)
class Accepted:
    kind: str                            # "image" か "pdf"
    data: bytes = field(repr=False)      # API に送るバイト列（画像は作り直した JPEG、PDF は受け取ったまま）
    pdf_text: str = field(default="", repr=False)  # PDF から抜き出した文字（画像・文字の無い PDF は ""）


def prepare_image(raw: bytes, fmt: str) -> bytes:
    limit = settings.image_max_long_edge
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise unsupported() from None
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)  # exif= を渡さないので EXIF（位置情報を含む）は書き出されない
    return out.getvalue()


def check_pdf(raw: bytes) -> None:
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れた PDF に pypdf はさまざまな例外を投げる。種類を問わず「開けない」と扱う
        raise unsupported() from None
    if pages == 0:
        raise unsupported()
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)


def accept_receipt(raw: bytes) -> Accepted:
    """中身で画像か PDF かを決め、API に送る形にそろえる。どちらでもなければ 415。"""
    fmt = sniff(raw)
    if fmt is None:
        raise unsupported()
    if fmt == "PDF":
        check_pdf(raw)
        return Accepted("pdf", raw, extract_text(raw))
    return Accepted("image", prepare_image(raw, fmt))
