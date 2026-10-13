"""画像の受付と前処理（セッション4の intake.py のコピー。縮小の上限と JPEG の品質を引数にした）。

前処理の設定は応答キャッシュのキーの材料になるので、関数の中に埋め込まず、呼び出し側から渡す。
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from kondate.settings import get_settings

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める（セッション2）

MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
]

MSG_TOO_LARGE = f"画像は {get_settings().upload_max_bytes // (1024 * 1024)}MB 以下にしてください"
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像を送ってください"


class Rejected(Exception):
    """受け付けられないファイル。status・type・message は利用者にそのまま返す固定の値。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def sniff_image(raw: bytes) -> str | None:
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
    original_size: tuple[int, int]
    sent_size: tuple[int, int]
    exif_removed: bool

    def info(self) -> dict:
        return {
            "original_size": list(self.original_size), "sent_size": list(self.sent_size),
            "media_type": self.media_type, "exif_removed": self.exif_removed, "bytes": len(self.data),
        }


def accept_image(raw: bytes, max_long_edge: int, quality: int) -> PreparedImage:
    """中身で画像かどうかを確かめ、向きを直し・縮め・EXIF を捨てた JPEG に作り直す。"""
    fmt = sniff_image(raw)
    if fmt is None:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED)
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            had_exif = len(img.getexif()) > 0
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED) from None
    original = img.size
    img.thumbnail((max_long_edge, max_long_edge))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)  # exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", original, img.size, had_exif)
