"""復習1で使う部品：セッション2〜4の本文のコードを1つにまとめて写したもの。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。値と固定文は本文と同じ。
- セッション2：受付の検査（inspect_upload）。PDF も受け付ける /api/uploads の規則
- セッション3：前処理（prepare_image）・画像トークンの見積もり（estimate_image_tokens）・image ブロック（base64_block）
- セッション4：食材リストのモデル（FridgeScan）・読み取りと再試行（scan_fridge）・要確認（find_issues）・
  レシピ検索（search_recipes）・画像だけを受け付ける /api/fridge/scan の受付（accept_image）
"""

from __future__ import annotations

import base64
import io
import logging
import math
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Literal

import anthropic
from anthropic import transform_schema
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from pypdf import PdfReader

from kondate.data import load_recipes
from kondate.llm import ChatRequest, LLMProvider, Usage
from kondate.settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# ============================================================== セッション2：受付の検査

UPLOAD_MAX_BYTES = settings.upload_max_bytes  # 10MiB
Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める
MAX_PDF_PAGES = 200

IMAGE_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
]

MSG_TOO_LARGE = f"ファイルは {UPLOAD_MAX_BYTES // (1024 * 1024)}MB 以下にしてください"
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_TOO_MANY_PAGES = f"PDF は {MAX_PDF_PAGES} ページ以下にしてください"
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"


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


def check_image(raw: bytes, fmt: str) -> str:
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            return IMAGE_EXT[img.format]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED) from None


def check_pdf(raw: bytes) -> str:
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED) from None
    if pages == 0:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED)
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    return "pdf"


def inspect_upload(raw: bytes) -> tuple[str, str]:
    """中身だけを見て (kind, 拡張子) を決める。バイト数の検査（10MiB）は呼び出す側で先に行う。"""
    fmt = sniff(raw)
    if fmt is None:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED)
    if fmt == "PDF":
        return "pdf", check_pdf(raw)
    return "image", check_image(raw, fmt)


# ============================================================== セッション3：見積もりと前処理

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
API_MAX_LONG_EDGE = 2576
API_MAX_IMAGE_TOKENS = 4784
PATCH = 28


def base64_block(data: bytes, media_type: str = "image/jpeg") -> dict:
    encoded = base64.standard_b64encode(data).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}


def estimate_image_tokens(width: int, height: int) -> int:
    """寸法から画像トークンを見積もる（mockllm と同じ近似式。本物の課金とは一致しない）。"""
    scale = min(1.0, API_MAX_LONG_EDGE / max(width, height))
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return min(API_MAX_IMAGE_TOKENS, math.ceil(w / PATCH) * math.ceil(h / PATCH))


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

    def info(self) -> dict:
        """/api/fridge/scan の応答の image（セッション4）。"""
        return {
            "original_size": list(self.original_size), "sent_size": list(self.sent_size),
            "media_type": self.media_type, "exif_removed": self.exif_removed, "bytes": len(self.data),
        }


def prepare_image(raw: bytes, max_long_edge: int | None = None, quality: int = 90, fmt: str | None = None) -> PreparedImage:
    """向きを直し、長辺を上限まで縮め、EXIF（位置情報を含む）を捨てて JPEG に作り直す。"""
    limit = max_long_edge or settings.image_max_long_edge
    with Image.open(io.BytesIO(raw), formats=[fmt] if fmt else None) as img:
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValueError(f"unsupported:{img.format}")
        stored = img.size
        had_exif = len(img.getexif()) > 0
        img = ImageOps.exif_transpose(img).convert("RGB")
    original = img.size
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return PreparedImage(out.getvalue(), "image/jpeg", stored, original, img.size, had_exif)


# ============================================================== セッション4：/api/fridge/scan の受付（画像だけ）

SCAN_MSG_TOO_LARGE = f"画像は {UPLOAD_MAX_BYTES // (1024 * 1024)}MB 以下にしてください"
SCAN_MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像を送ってください"
MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
MSG_UPSTREAM = "画像の読み取りに失敗しました。時間をおいて試してください"


def accept_image(raw: bytes) -> PreparedImage:
    """中身で画像かどうかを確かめ、送ってよい形に作り直す。PDF は受け付けない。"""
    fmt = sniff(raw)
    if fmt is None or fmt == "PDF":
        raise Rejected(415, "unsupported_media", SCAN_MSG_UNSUPPORTED)
    try:
        return prepare_image(raw, fmt=fmt)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", SCAN_MSG_UNSUPPORTED) from None


# ============================================================== セッション4：モデル・読み取り・再試行

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class Ingredient(BaseModel):
    name: Name = Field(description="食材の名前（例：キャベツ）")
    quantity: str = Field(description="見た目の分量（例：1/2玉）")
    amount: float = Field(gt=0, description="数量（例：0.5）")
    unit: str = Field(description="数量の単位（例：玉）")
    confidence: float = Field(ge=0, le=1, description="読み取りの確からしさ（0〜1）")
    category: str = Field(description="食材の分類（例：野菜）")


class FridgeScan(BaseModel):
    ingredients: list[Ingredient]


FRIDGE_SCHEMA = transform_schema(FridgeScan)
FRIDGE_PROMPT = "冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。"
MAX_ATTEMPTS = 2  # 1回目＋再試行1回


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった（SDK の再試行も尽きた）。"""


class InvalidOutput(Exception):
    """応答はあったが、食材リストとして使えなかった。usage はそこまでの全試行の合計。"""

    def __init__(self, reason: str, attempts: int, usage: Usage) -> None:
        super().__init__(reason)
        self.reason, self.attempts, self.usage = reason, attempts, usage


@dataclass(frozen=True)
class ScanResult:
    scan: FridgeScan
    attempts: int
    usage: Usage  # すべての試行の合計


def build_request(jpeg: bytes, max_tokens: int | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": [base64_block(jpeg), {"type": "text", "text": FRIDGE_PROMPT}]}],
        output_schema=FRIDGE_SCHEMA,
        max_tokens=max_tokens or settings.llm_max_tokens,
    )


def error_summary(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}" for err in e.errors()]


async def scan_fridge(llm: LLMProvider, jpeg: bytes, max_tokens: int | None = None) -> ScanResult:
    req = build_request(jpeg, max_tokens)
    used_in = used_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await llm.complete(req)
        except anthropic.APIError as e:
            raise UpstreamUnavailable() from e
        used_in += result.usage.input_tokens
        used_out += result.usage.output_tokens
        usage = Usage(used_in, used_out)
        if result.stop_reason == "max_tokens":
            log.warning("fridge scan: max_tokens で打ち切られました（%d回目）", attempt)
            raise InvalidOutput("max_tokens", attempt, usage)
        try:
            return ScanResult(FridgeScan.model_validate_json(result.text), attempt, usage)
        except ValidationError as e:
            log.warning("fridge scan: 検証に失敗しました（%d回目）: %s", attempt, error_summary(e))
    raise InvalidOutput("validation", MAX_ATTEMPTS, usage)


# ============================================================== セッション4：要確認

REVIEW_CONFIDENCE = 0.6
MSG_LOW_CONFIDENCE = "読み取りの確からしさが低い食材です。写真と合っているか確かめてください"
MSG_UNKNOWN_NAME = "食材辞書にない名前です。名前が正しいか確かめてください"


@lru_cache
def ingredient_dictionary() -> frozenset[str]:
    return frozenset(i["name"] for r in load_recipes() for i in r["ingredients"])


def find_issues(ingredients: list[Ingredient], dictionary: frozenset[str] | None = None) -> list[dict]:
    known = ingredient_dictionary() if dictionary is None else dictionary
    issues: list[dict] = []
    for index, ing in enumerate(ingredients):
        if ing.confidence < REVIEW_CONFIDENCE:
            issues.append({"index": index, "name": ing.name, "reason": "low_confidence", "message": MSG_LOW_CONFIDENCE})
        if ing.name not in known:
            issues.append({"index": index, "name": ing.name, "reason": "unknown_name", "message": MSG_UNKNOWN_NAME})
    return issues


def confirmed_names(ingredients: list[Ingredient], issues: list[dict]) -> list[str]:
    """要確認の印が1つも付いていない食材の名前（重複を除き、順序は保つ）。"""
    flagged = {i["index"] for i in issues}
    return list(dict.fromkeys(ing.name for index, ing in enumerate(ingredients) if index not in flagged))


# ============================================================== セッション4：レシピ検索

Allergen = Literal["卵", "乳", "小麦", "えび", "かに", "落花生", "そば"]
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
MAX_INGREDIENTS = 10


class SearchRecipesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredients: list[Word] = Field(default_factory=list, max_length=MAX_INGREDIENTS)
    max_minutes: int | None = Field(default=None, ge=1, le=240)
    exclude_allergens: list[Allergen] = Field(default_factory=list)
    tags: list[Word] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=5, ge=1, le=10)


def search_recipes(args: SearchRecipesIn) -> dict:
    """一致した指定語の多い順 → minutes の昇順 → id の昇順（決定的）。"""
    words = list(dict.fromkeys(args.ingredients))
    hits: list[tuple[int, dict]] = []
    for r in load_recipes():
        if args.max_minutes is not None and r["minutes"] > args.max_minutes:
            continue
        if set(args.exclude_allergens) & set(r["allergens"]):
            continue
        if not set(args.tags) <= set(r["tags"]):
            continue
        names = [i["name"] for i in r["ingredients"]]
        matched = sum(1 for w in words if any(w in n for n in names))
        if words and matched == 0:
            continue
        hits.append((matched, r))
    hits.sort(key=lambda h: (-h[0], h[1]["minutes"], h[1]["id"]))
    return {"recipes": [{k: r[k] for k in ("id", "name", "minutes", "kcal", "tags")} for _, r in hits[: args.limit]]}


def to_search_args(names: list[str], max_minutes: int | None = None) -> SearchRecipesIn:
    """確認済みの食材名を search_recipes の入力にする。LLM に選ばせず、アプリのコードで組み立てる。"""
    return SearchRecipesIn(ingredients=names[:MAX_INGREDIENTS], max_minutes=max_minutes)
