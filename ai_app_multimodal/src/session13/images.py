"""画像の前処理（セッション3の images.py から prepare_image だけをコピー）。本章では「送る前・保存する前の検査」に使う。"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from kondate.settings import get_settings

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # 解凍爆弾の拒否（セッション2と同じ値）


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    stored_size: tuple[int, int]    # ファイルに保存されていた画素の寸法
    original_size: tuple[int, int]  # 向きを直したあとの寸法
    sent_size: tuple[int, int]      # 縮小したあと＝API に送る寸法
    exif_removed: bool


def prepare_image(raw: bytes, max_long_edge: int | None = None, quality: int = 90) -> PreparedImage:
    """向きを直し、長辺を上限まで縮め、EXIF（位置情報を含む）を捨てて JPEG に作り直す。"""
    limit = max_long_edge or get_settings().image_max_long_edge
    with Image.open(io.BytesIO(raw)) as img:
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValueError(f"unsupported:{img.format}")
        stored = img.size
        had_exif = len(img.getexif()) > 0
        img = ImageOps.exif_transpose(img).convert("RGB")  # ① EXIF を捨てる前に、向きを画素へ反映する
    original = img.size
    img.thumbnail((limit, limit))                          # ② 縦横比を保って長辺を limit 以下に（拡大はしない）
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)                 # ③ exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", stored, original, img.size, had_exif)
