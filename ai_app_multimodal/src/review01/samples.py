"""復習1の入力を作る。どれも fridge.jpg などの検証用メディアから決定的に作る（実写は使わない）。"""

from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image

from kondate.media import media_path
from src.review01.kit import UPLOAD_MAX_BYTES

ORIENTATION = 0x0112  # EXIF の Orientation タグ
TEXT = "鶏むね肉 1枚\n".encode()


def fridge() -> bytes:
    """1280×960 の JPEG。ダミーの EXIF と位置情報（GPS）付き。"""
    return media_path("fridge.jpg").read_bytes()


def receipt_png() -> bytes:
    """600×900 の PNG。"""
    return media_path("receipt.png").read_bytes()


def recipe_pdf() -> bytes:
    """3ページの PDF。"""
    return media_path("recipe_book.pdf").read_bytes()


def text_file() -> bytes:
    """ただの文章。名前だけ .png にして送られてきた、という想定で使う。"""
    return TEXT


def broken_png() -> bytes:
    """先頭8バイトだけ PNG の署名で、後ろはただの文章。"""
    return b"\x89PNG\r\n\x1a\n" + TEXT


@lru_cache
def portrait() -> bytes:
    """画素は横倒し（960×1280）で保存し、向きは EXIF の Orientation=6 で伝える写真。位置情報も引き継ぐ。"""
    with Image.open(media_path("fridge.jpg")) as img:
        exif = img.getexif()
        stored = img.transpose(Image.Transpose.ROTATE_90)
    exif[ORIENTATION] = 6
    buf = io.BytesIO()
    stored.save(buf, "JPEG", quality=85, exif=exif)
    return buf.getvalue()


@lru_cache
def large() -> bytes:
    """高画素のスマホで撮ったつもりの 4000×3000 版。EXIF（位置情報を含む）はそのまま引き継ぐ。"""
    with Image.open(media_path("fridge.jpg")) as img:
        exif = img.getexif()
        big = img.resize((4000, 3000), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    big.save(buf, "JPEG", quality=85, exif=exif)
    return buf.getvalue()


@lru_cache
def huge_png() -> bytes:
    """8000×6000（4800万画素）の真っ黒な PNG。圧縮後は小さいが、開くと大きい（解凍爆弾の形）。"""
    buf = io.BytesIO()
    Image.new("L", (8000, 6000)).save(buf, "PNG")
    return buf.getvalue()


def oversize() -> bytes:
    """10MiB を1バイトだけ超えるファイル（先頭は JPEG の署名）。"""
    return b"\xff\xd8\xff" + bytes(UPLOAD_MAX_BYTES + 1 - 3)
