"""受付検査と前処理（セッション2・6・7・14の受付を1つにまとめたもの）。

- inspect_upload・save_upload … セッション2（保存先のパスを返すのはセッション13）
- accept_image … セッション14（縮小の上限と JPEG の品質を引数で受け取る。応答キャッシュのキーの材料になるため）
- accept_receipt … セッション7（画像の作り直しは accept_image と同じ処理を使う）
- inspect_pdf … セッション6
各セッションでは同じ形の Rejected を別々に持っていたので、1つにそろえた。固定文は各セッションのまま。
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader

from kondate.settings import get_settings
from src.final.documents import extract_pages
from src.final.pdftext import extract_text

settings = get_settings()

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める（セッション2）
MAX_PDF_PAGES = 200
JPEG_QUALITY = 90

IMAGE_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
]

_MB = settings.upload_max_bytes // (1024 * 1024)
MSG_TOO_LARGE = f"ファイルは {_MB}MB 以下にしてください"
MSG_IMAGE_TOO_LARGE = f"画像は {_MB}MB 以下にしてください"          # 冷蔵庫の写真（セッション4）
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"
MSG_UNSUPPORTED_IMAGE = "JPEG・PNG・WebP・GIF の画像を送ってください"
MSG_NOT_PDF = "PDF を送ってください"


class Rejected(Exception):
    """受け付けられないファイル。status・type・message は利用者にそのまま返す固定の値。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def unsupported(message: str = MSG_UNSUPPORTED) -> Rejected:
    return Rejected(415, "unsupported_media", message)


def sniff(raw: bytes) -> str | None:
    """先頭のバイト（マジックバイト）から形式の候補を返す。あくまで候補で、確定ではない。"""
    for magic, fmt in MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


# ---------------------------------------------------------------- アップロード（セッション2・13）

def check_image(raw: bytes, fmt: str) -> str:
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            return IMAGE_EXT[img.format]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise unsupported() from None


def count_pdf_pages(raw: bytes, message: str) -> int:
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:  # 壊れた PDF に pypdf はさまざまな例外を投げる。種類を問わず「開けない」と扱う
        raise unsupported(message) from None
    if pages == 0:
        raise unsupported(message)
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    return pages


def inspect_upload(raw: bytes) -> tuple[str, str]:
    """中身だけを見て (kind, 拡張子) を決める。"""
    fmt = sniff(raw)
    if fmt is None:
        raise unsupported()
    if fmt == "PDF":
        count_pdf_pages(raw, MSG_UNSUPPORTED)
        return "pdf", "pdf"
    return "image", check_image(raw, fmt)


def save_upload(dest: Path, upload_id: str, ext: str, raw: bytes) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{upload_id}.{ext}"
    with path.open("xb") as f:  # "x"：同じ名前があれば上書きせずに失敗する
        f.write(raw)
    return path


# ---------------------------------------------------------------- 画像の作り直し（セッション3・4・14）

@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    original_size: tuple[int, int]
    sent_size: tuple[int, int]
    exif_removed: bool

    def info(self) -> dict:
        return {
            "original_size": list(self.original_size), "sent_size": list(self.sent_size),
            "media_type": self.media_type, "exif_removed": self.exif_removed, "bytes": len(self.data),
        }


def _reencode(raw: bytes, fmt: str, max_long_edge: int, quality: int, message: str) -> PreparedImage:
    """向きを直し・縮め・EXIF（位置情報を含む）を捨てた JPEG に作り直す。"""
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            had_exif = len(img.getexif()) > 0
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise unsupported(message) from None
    original = img.size
    img.thumbnail((max_long_edge, max_long_edge))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)  # exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", original, img.size, had_exif)


def accept_image(raw: bytes, max_long_edge: int, quality: int) -> PreparedImage:
    fmt = sniff(raw)
    if fmt is None or fmt == "PDF":
        raise unsupported(MSG_UNSUPPORTED_IMAGE)
    return _reencode(raw, fmt, max_long_edge, quality, MSG_UNSUPPORTED_IMAGE)


# ---------------------------------------------------------------- レシート（セッション7）

@dataclass(frozen=True)
class Accepted:
    kind: str                                      # "image" か "pdf"
    data: bytes = field(repr=False)                # API に送るバイト列
    pdf_text: str = field(default="", repr=False)  # PDF から抜き出した文字（画像は ""）


def accept_receipt(raw: bytes) -> Accepted:
    fmt = sniff(raw)
    if fmt is None:
        raise unsupported()
    if fmt == "PDF":
        count_pdf_pages(raw, MSG_UNSUPPORTED)
        return Accepted("pdf", raw, extract_text(raw))
    prepared = _reencode(raw, fmt, settings.image_max_long_edge, JPEG_QUALITY, MSG_UNSUPPORTED)
    return Accepted("image", prepared.data)


# ---------------------------------------------------------------- 文書（セッション5・6）

def inspect_pdf(raw: bytes) -> tuple[int, list[str]]:
    """中身で PDF かどうかを確かめ、(ページ数, ページごとの抽出テキスト) を返す。"""
    if not raw.startswith(b"%PDF-"):
        raise unsupported(MSG_NOT_PDF)
    pages = count_pdf_pages(raw, MSG_NOT_PDF)
    try:
        texts = extract_pages(raw)
    except Exception:
        texts = [""] * pages
    return pages, texts
