"""受付検査と前処理（中間プロジェクト1）。セッション2・3・4・5・7 の受付を1つのファイルにまとめたもの。

窓口（エンドポイント）ごとに、受け付ける種類と断るときの固定文は各セッションで決めたものをそのまま使う。
- 冷蔵庫の写真（セッション4）：画像だけ。向きを直し、長辺を縮め、EXIF（位置情報を含む）を捨てた JPEG に作り直す
- レシート（セッション7）：画像か PDF。画像は写真と同じ前処理、PDF は受け取ったまま送り、文字を先に抜き出す
- レシピ本（セッション5・6）：PDF だけ
形式は中身（マジックバイト → Pillow・pypdf で開けるか）で決める。ファイル名と Content-Type は見ない（セッション2）。
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field

from PIL import Image, ImageOps
from pypdf import PdfReader

from kondate.settings import get_settings
from src.mid01.pdftext import extract_text

settings = get_settings()

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める（セッション2）
MAX_PDF_PAGES = 200
MB = settings.upload_max_bytes // (1024 * 1024)

MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
]

# ---- 固定文（各セッションで決めたもの。窓口ごとに使い分ける） ----
MSG_FILE_TOO_LARGE = f"ファイルは {MB}MB 以下にしてください"                # レシート・レシピ本
MSG_IMAGE_TOO_LARGE = f"画像は {MB}MB 以下にしてください"                  # 冷蔵庫の写真
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"
MSG_NOT_IMAGE = "JPEG・PNG・WebP・GIF の画像を送ってください"               # 冷蔵庫の写真
MSG_NOT_IMAGE_OR_PDF = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"  # レシート
MSG_NOT_PDF = "PDF を送ってください"                                       # レシピ本


class Rejected(Exception):
    """受け付けられないファイル。status・type・message は利用者にそのまま返す固定の値。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def sniff(raw: bytes) -> str | None:
    """先頭のバイト（マジックバイト）から形式の候補を返す。あくまで候補で、確定ではない。"""
    for magic, fmt in MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    original_size: tuple[int, int]  # 向きを直したあとの寸法
    sent_size: tuple[int, int]      # 縮小したあと＝API に送る寸法
    exif_removed: bool

    def info(self) -> dict:
        return {
            "original_size": list(self.original_size), "sent_size": list(self.sent_size),
            "media_type": self.media_type, "exif_removed": self.exif_removed, "bytes": len(self.data),
        }


def prepare_image(raw: bytes, fmt: str, unsupported: str) -> PreparedImage:
    """候補の形式で開けるか確かめ、送ってよい形（向きを直した・縮めた・EXIF の無い JPEG）に作り直す。"""
    limit = settings.image_max_long_edge
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            had_exif = len(img.getexif()) > 0
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", unsupported) from None
    original = img.size
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)  # exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", original, img.size, had_exif)


def count_pdf_pages(raw: bytes, unsupported: str) -> int:
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れた PDF に pypdf はさまざまな例外を投げる。種類を問わず「開けない」と扱う
        raise Rejected(415, "unsupported_media", unsupported) from None
    if pages == 0:
        raise Rejected(415, "unsupported_media", unsupported)
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    return pages


# ---------------------------------------------------------------- 窓口ごとの受付

def accept_image(raw: bytes) -> PreparedImage:
    """冷蔵庫の写真（セッション4）。画像でなければ 415。"""
    fmt = sniff(raw)
    if fmt is None or fmt == "PDF":
        raise Rejected(415, "unsupported_media", MSG_NOT_IMAGE)
    return prepare_image(raw, fmt, MSG_NOT_IMAGE)


@dataclass(frozen=True)
class AcceptedReceipt:
    kind: str                                      # "image" か "pdf"
    data: bytes = field(repr=False)                # API に送るバイト列
    pdf_text: str = field(default="", repr=False)  # PDF から抜き出した文字（画像・文字の無い PDF は ""）


def accept_receipt(raw: bytes) -> AcceptedReceipt:
    """レシート（セッション7）。画像か PDF でなければ 415。"""
    fmt = sniff(raw)
    if fmt is None:
        raise Rejected(415, "unsupported_media", MSG_NOT_IMAGE_OR_PDF)
    if fmt == "PDF":
        count_pdf_pages(raw, MSG_NOT_IMAGE_OR_PDF)
        return AcceptedReceipt("pdf", raw, extract_text(raw))
    return AcceptedReceipt("image", prepare_image(raw, fmt, MSG_NOT_IMAGE_OR_PDF).data)


def accept_pdf(raw: bytes) -> int:
    """レシピ本（セッション5・6）。PDF でなければ 415。ページ数を返す。"""
    if sniff(raw) != "PDF":
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    return count_pdf_pages(raw, MSG_NOT_PDF)
