"""決定的な usage 計算（mockllm 独自の近似式。実際の課金とは一致しない）。

式は README.md「usage の計算式」と同じ。変更したら README も直すこと。
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
from dataclasses import dataclass, field

from PIL import Image
from pypdf import PdfReader

BASE_OVERHEAD = 4
MESSAGE_OVERHEAD = 3
IMAGE_MAX_LONG_EDGE = 2576
IMAGE_PATCH = 28
IMAGE_MAX_TOKENS = 4784
IMAGE_UNKNOWN_SIZE_TOKENS = 1600
PDF_TOKENS_PER_PAGE = 1600
PDF_MAX_PAGES = 600
IMAGE_MAX_PIXELS_EDGE = 8000
CACHE_MIN_TOKENS = 1024

IMAGE_MEDIA_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}


class InvalidContent(ValueError):
    """リクエスト中のコンテンツが処理できない（400 invalid_request_error にする）。"""


def text_tokens(text: str | None) -> int:
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / 3)


def json_tokens(value: object) -> int:
    return text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def image_tokens(width: int, height: int) -> int:
    scale = min(1.0, IMAGE_MAX_LONG_EDGE / max(width, height))
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return min(IMAGE_MAX_TOKENS, math.ceil(w / IMAGE_PATCH) * math.ceil(h / IMAGE_PATCH))


def _b64decode(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidContent(f"base64 のデコードに失敗しました: {e}") from e


def inspect_image(media_type: str, data_b64: str) -> tuple[int, int]:
    if media_type not in IMAGE_MEDIA_TYPES:
        raise InvalidContent(
            f"image.source.media_type '{media_type}' は未対応です（{', '.join(IMAGE_MEDIA_TYPES)} のいずれか）"
        )
    raw = _b64decode(data_b64)
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt = img.format
            width, height = img.size
    except Exception as e:  # Pillow は形式ごとに例外型が違う
        raise InvalidContent(f"画像として解析できません: {e}") from e
    if fmt != IMAGE_MEDIA_TYPES[media_type]:
        raise InvalidContent(
            f"Image does not match the provided media type {media_type}（実際の形式は {fmt}）"
        )
    if max(width, height) > IMAGE_MAX_PIXELS_EDGE:
        raise InvalidContent(f"画像の一辺が {IMAGE_MAX_PIXELS_EDGE}px を超えています（{width}×{height}）")
    return width, height


def inspect_pdf(data_b64: str) -> int:
    raw = _b64decode(data_b64)
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception as e:
        raise InvalidContent(f"PDF として解析できません: {e}") from e
    if pages > PDF_MAX_PAGES:
        raise InvalidContent(f"PDF のページ数が上限 {PDF_MAX_PAGES} を超えています（{pages} ページ）")
    return pages


@dataclass
class MediaSummary:
    image_sizes: list[tuple[int, int] | None] = field(default_factory=list)
    pdf_pages: list[int | None] = field(default_factory=list)
    text_documents: int = 0


def anthropic_block_tokens(block: dict, media: MediaSummary) -> int:
    btype = block.get("type")
    if btype == "text":
        return text_tokens(block.get("text", ""))
    if btype == "image":
        src = block.get("source") or {}
        if src.get("type") == "base64":
            w, h = inspect_image(src.get("media_type", ""), src.get("data", ""))
            media.image_sizes.append((w, h))
            return image_tokens(w, h)
        if src.get("type") in ("url", "file"):
            media.image_sizes.append(None)
            return IMAGE_UNKNOWN_SIZE_TOKENS
        raise InvalidContent(f"image.source.type '{src.get('type')}' は未対応です")
    if btype == "document":
        src = block.get("source") or {}
        stype = src.get("type")
        if stype == "base64":
            if src.get("media_type") != "application/pdf":
                raise InvalidContent("document の base64 は media_type 'application/pdf' のみ受け付けます")
            pages = inspect_pdf(src.get("data", ""))
            media.pdf_pages.append(pages)
            return pages * PDF_TOKENS_PER_PAGE
        if stype == "text":
            media.text_documents += 1
            return text_tokens(src.get("data", ""))
        if stype == "content":
            media.text_documents += 1
            return sum(anthropic_block_tokens(b, media) for b in src.get("content", []))
        if stype in ("url", "file"):
            media.pdf_pages.append(None)
            return PDF_TOKENS_PER_PAGE
        raise InvalidContent(f"document.source.type '{stype}' は未対応です")
    if btype == "tool_use":
        return text_tokens(block.get("name", "")) + json_tokens(block.get("input", {}))
    if btype == "tool_result":
        content = block.get("content", "")
        if isinstance(content, str):
            return text_tokens(content)
        return sum(anthropic_block_tokens(b, media) for b in content or [])
    return 0


def output_tokens(content: list[dict]) -> int:
    total = 0
    for block in content:
        if block["type"] == "text":
            total += text_tokens(block["text"])
        elif block["type"] == "tool_use":
            total += text_tokens(block["name"]) + json_tokens(block["input"])
    return max(1, total)
