"""受付検査と前処理（セッション2・3のコードを、画像だけに絞ってコピーしたもの）。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。
- 形式は中身（マジックバイト → Pillow で開けるか）で決める。名前と Content-Type は見ない（セッション2）
- 向きを直し、長辺を上限まで縮め、EXIF（位置情報を含む）を捨てて JPEG に作り直す（セッション3）
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
    """受け付けられない画像。status・type・message は利用者にそのまま返す固定の値。"""

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
    original_size: tuple[int, int]  # 向きを直したあとの寸法
    sent_size: tuple[int, int]      # 縮小したあと＝API に送る寸法
    exif_removed: bool

    def info(self) -> dict:
        return {
            "original_size": list(self.original_size), "sent_size": list(self.sent_size),
            "media_type": self.media_type, "exif_removed": self.exif_removed, "bytes": len(self.data),
        }


def accept_image(raw: bytes) -> PreparedImage:
    """中身で画像かどうかを確かめ、送ってよい形（向きを直した・縮めた・EXIF の無い JPEG）に作り直す。"""
    fmt = sniff_image(raw)
    if fmt is None:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED)
    limit = get_settings().image_max_long_edge
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            had_exif = len(img.getexif()) > 0
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED) from None
    original = img.size
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)  # exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", original, img.size, had_exif)
