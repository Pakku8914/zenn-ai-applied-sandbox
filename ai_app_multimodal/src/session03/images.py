"""image ブロックの組み立て・画像トークンの見積もり・前処理（セッション3）。"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps

from kondate.settings import get_settings

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # 解凍爆弾の拒否（セッション2と同じ値）

# API 側の画像の上限（2026-10-02 時点）。mockllm もこの値で近似している
API_MAX_LONG_EDGE = 2576
API_MAX_IMAGE_TOKENS = 4784
PATCH = 28  # 28×28 画素で約1トークン


# ---------------------------------------------------------------- image ブロックの3つの渡し方

def base64_block(data: bytes, media_type: str = "image/jpeg") -> dict:
    """画像の中身をリクエストに同封する。"""
    encoded = base64.standard_b64encode(data).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}


def url_block(url: str) -> dict:
    """API 側に URL から取りに行ってもらう（URL は API から見えなければならない）。"""
    return {"type": "image", "source": {"type": "url", "url": url}}


def file_block(file_id: str) -> dict:
    """Files API に預けた画像を file_id で参照する。"""
    return {"type": "image", "source": {"type": "file", "file_id": file_id}}


# ---------------------------------------------------------------- 画像トークンの見積もり

def estimate_image_tokens(width: int, height: int) -> int:
    """寸法から画像トークンを見積もる（mockllm と同じ近似式。本物の課金とは一致しない）。"""
    scale = min(1.0, API_MAX_LONG_EDGE / max(width, height))  # 長辺 2576px を超えたら縮小（拡大はしない）
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return min(API_MAX_IMAGE_TOKENS, math.ceil(w / PATCH) * math.ceil(h / PATCH))


# ---------------------------------------------------------------- 前処理

@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    stored_size: tuple[int, int]    # ファイルに保存されていた画素の寸法
    original_size: tuple[int, int]  # 向きを直したあとの寸法
    sent_size: tuple[int, int]      # 縮小したあと＝API に送る寸法
    exif_removed: bool

    @property
    def tokens(self) -> int:
        return estimate_image_tokens(*self.sent_size)


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
