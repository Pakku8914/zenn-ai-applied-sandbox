"""復習2で使う部品：セッション2〜7の本文のコードを1つにまとめて写したもの。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。値と固定文は本文と同じ。
- セッション2：受付の検査（inspect_upload）。/api/uploads の規則
- セッション3：画像トークンの見積もり（estimate_image_tokens）
- セッション4：食材のモデル（Ingredient）と要確認（find_issues）
- セッション5・6：document ブロック・引用の検証・PDF だけの受付（inspect_pdf）・見出しの索引・ページ選択・
  ask の部品（choose_pages・selected_pdf・grounded_answer）・分割取り込み（import_recipes）・答えを知っている Fake
- セッション7：レシートの受付（accept_receipt）・読み取り（read_receipt）・整合性検査（check_receipt）・
  PDF の文字との突き合わせ（parse_receipt_text・compare_with_text）
- 共通：結果の入れ物（Outcome）と、LLM の呼び出し回数を数える Counting
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import re
import unicodedata
import warnings
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from typing import Annotated

import anthropic
import anyio
from anthropic import transform_schema
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from pypdf import PdfReader, PdfWriter

from kondate.data import load_recipes
from kondate.llm import ChatRequest, ChatResult, LLMProvider, StreamEvent, Usage
from kondate.settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# ============================================================== 共通：結果の入れ物と呼び出し回数

NO_USAGE = Usage(0, 0)


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict                 # 利用者に返す本文（request_id は HTTP の層で足す）
    usage: Usage = NO_USAGE    # 記録用。502 でも、試行したぶんの合計が入る


def failure(status: int, type_: str, message: str, usage: Usage = NO_USAGE) -> Outcome:
    return Outcome(status, {"error": {"type": type_, "message": message}}, usage)


def sum_usage(used: Iterable[Usage]) -> Usage:
    used = list(used)
    return Usage(
        sum(u.input_tokens for u in used), sum(u.output_tokens for u in used),
        sum(u.cache_read_input_tokens for u in used), sum(u.cache_creation_input_tokens for u in used),
    )


class Counting:
    """LLMProvider を包み、complete が呼ばれた回数を数える。"""

    name = "counting"

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.calls = inner, 0

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        return await self.inner.complete(req)

    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        return self.inner.stream(req)


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


# ============================================================== セッション3：画像トークンの見積もり

API_MAX_LONG_EDGE = 2576
API_MAX_IMAGE_TOKENS = 4784
PATCH = 28


def estimate_image_tokens(width: int, height: int) -> int:
    """寸法から画像トークンを見積もる（mockllm と同じ近似式。本物の課金とは一致しない）。"""
    scale = min(1.0, API_MAX_LONG_EDGE / max(width, height))
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return min(API_MAX_IMAGE_TOKENS, math.ceil(w / PATCH) * math.ceil(h / PATCH))


# ============================================================== セッション4：食材のモデルと要確認

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class Ingredient(BaseModel):
    name: Name = Field(description="食材の名前（例：キャベツ）")
    quantity: str = Field(description="見た目の分量（例：1/2玉）")
    amount: float = Field(gt=0, description="数量（例：0.5）")
    unit: str = Field(description="数量の単位（例：玉）")
    confidence: float = Field(ge=0, le=1, description="読み取りの確からしさ（0〜1）")
    category: str = Field(description="食材の分類（例：野菜）")


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


# ============================================================== セッション5：document ブロック・抽出・引用の検証

PDF_TOKENS_PER_PAGE = 1600  # mockllm の近似
MIN_QUOTE_CHARS = 6


def pdf_block(raw: bytes) -> dict:
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def cached(block: dict) -> dict:
    """このブロックまで（system も含む）を、プロンプトキャッシュの接頭辞にする印を付ける（セッション6）。"""
    return {**block, "cache_control": {"type": "ephemeral"}}


def extract_pages(raw: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(raw))
    return [page.extract_text() or "" for page in reader.pages]


def normalize(text: str) -> str:
    """照合用にそろえる。NFKC（全角英数・全角空白・康熙部首を通常の文字へ）→ 空白と改行をすべて除く。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class CitationCheck:
    page: int
    quote: str
    ok: bool
    reason: str  # ok / too_short / page_out_of_range / not_found


def check_citation(page_texts: list[str], page: int, quote: str) -> CitationCheck:
    """引用文 quote が、page ページ目（1始まり）の抽出結果に本当にあるかを確かめる。"""
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return CitationCheck(page, quote, False, "too_short")
    if not 1 <= page <= len(page_texts):
        return CitationCheck(page, quote, False, "page_out_of_range")
    if q not in normalize(page_texts[page - 1]):
        return CitationCheck(page, quote, False, "not_found")
    return CitationCheck(page, quote, True, "ok")


MSG_NOT_PDF = "PDF を送ってください"
DOC_MSG_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
MAX_ATTEMPTS = 2  # 最初の1回＋再試行1回（セッション4・5・6・7で共通）
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)


def inspect_pdf(raw: bytes) -> tuple[int, list[str]]:
    """/api/documents の受付（セッション5・6）。中身で PDF かを確かめ、(ページ数, ページごとの抽出テキスト) を返す。"""
    if not raw.startswith(b"%PDF-"):
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    try:
        pages = len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF) from None
    if pages == 0:
        raise Rejected(415, "unsupported_media", MSG_NOT_PDF)
    if pages > MAX_PDF_PAGES:
        raise Rejected(413, "too_large", MSG_TOO_MANY_PAGES)
    try:
        texts = extract_pages(raw)
    except Exception:
        texts = [""] * pages
    return pages, texts


class Citation(BaseModel):
    page: int = Field(description="引用したページの番号（1始まり）")
    quote: str = Field(description="そのページから一字一句そのまま写した文")


class DocumentAnswer(BaseModel):
    answer: str
    citations: list[Citation]


ANSWER_SCHEMA = transform_schema(DocumentAnswer)


# ============================================================== セッション6：索引・ページ選択・分割

ASK_MAX_PAGES = 20
MSG_PAGES_COUNT = f"pages は 1〜{ASK_MAX_PAGES} 個で指定してください"
MSG_PAGES_REQUIRED = "読むページを決められませんでした。pages でページ番号を指定してください"
SELECTION_CACHE_SIZE = 8
HEADING = re.compile(r"(R\d{3})調理時間(\d+)分(\d+)人分1人分(\d+)kcal")


@dataclass(frozen=True)
class Heading:
    page: int
    recipe_id: str
    name: str
    minutes: int
    servings: int
    kcal: int


def parse_heading(text: str, page: int) -> Heading | None:
    t = normalize(text)
    m = HEADING.search(t)
    if m is None:
        return None
    return Heading(page, m[1], t[: m.start()], int(m[2]), int(m[3]), int(m[4]))


def build_index(page_texts: list[str]) -> list[Heading]:
    return [h for i, text in enumerate(page_texts, 1) if (h := parse_heading(text, i)) is not None]


def guess_pages(index: list[Heading], question: str) -> list[int]:
    q = normalize(question)
    return sorted({h.page for h in index if h.name and h.name in q})


def _write(reader: PdfReader, pages: list[int]) -> bytes:
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def select_pages(raw: bytes, pages: list[int]) -> bytes:
    return _write(PdfReader(io.BytesIO(raw)), pages)


def chunk_ranges(pages: int, size: int, overlap: int) -> list[tuple[int, int]]:
    if pages < 1 or not 0 <= overlap < size:
        raise ValueError("pages は 1 以上、overlap は 0 以上 size 未満にしてください")
    ranges: list[tuple[int, int]] = []
    start = 1
    while True:
        end = min(start + size - 1, pages)
        ranges.append((start, end))
        if end == pages:
            return ranges
        start = end - overlap + 1


def split_pdf(raw: bytes, ranges: list[tuple[int, int]]) -> list[bytes]:
    reader = PdfReader(io.BytesIO(raw))
    return [_write(reader, list(range(start, end + 1))) for start, end in ranges]


@dataclass
class Doc:
    """登録済みの文書（セッション6の StoredDocument から、ask に要る項目だけ）。"""

    data: bytes = field(repr=False)
    pages: int
    page_texts: list[str] = field(repr=False)
    index: list[Heading] = field(repr=False)
    selections: dict[tuple[int, ...], bytes] = field(default_factory=dict, repr=False)


def load_doc(raw: bytes) -> Doc:
    pages, texts = inspect_pdf(raw)
    return Doc(raw, pages, texts, build_index(texts))


def choose_pages(doc: Doc, question: str, pages: list[int] | None) -> list[int]:
    """送るページ（元の PDF のページ番号・昇順・重複なし）を決める。決められなければ Rejected(422)。"""
    if pages is not None:
        chosen = sorted(set(pages))
        if not 1 <= len(chosen) <= ASK_MAX_PAGES:
            raise Rejected(422, "invalid_request", MSG_PAGES_COUNT)
        if chosen[0] < 1 or chosen[-1] > doc.pages:
            raise Rejected(422, "invalid_request", f"pages は 1〜{doc.pages} の範囲で指定してください")
        return chosen
    if doc.pages <= ASK_MAX_PAGES:
        return list(range(1, doc.pages + 1))
    chosen = guess_pages(doc.index, question)
    if not 1 <= len(chosen) <= ASK_MAX_PAGES:
        raise Rejected(422, "invalid_request", MSG_PAGES_REQUIRED)
    return chosen


async def selected_pdf(doc: Doc, pages: list[int]) -> bytes:
    """選んだページの PDF。同じ組み合わせには前に作ったバイト列を返す（キャッシュの接頭辞を変えない）。"""
    if pages == list(range(1, doc.pages + 1)):
        return doc.data
    key = tuple(pages)
    if key not in doc.selections:
        doc.selections[key] = await anyio.to_thread.run_sync(select_pages, doc.data, pages)
        while len(doc.selections) > SELECTION_CACHE_SIZE:
            del doc.selections[next(iter(doc.selections))]
    return doc.selections[key]


def grounded_answer(text: str, page_texts: list[str], sent: list[int]) -> DocumentAnswer | None:
    """引用のページ番号（送った PDF の中での番号）を元の番号に戻し、元のページで実在を確かめる。"""
    try:
        answer = DocumentAnswer.model_validate_json(text)
    except ValidationError:
        return None
    if not answer.citations:
        return None
    citations = []
    for c in answer.citations:
        if not 1 <= c.page <= len(sent):
            return None
        original = sent[c.page - 1]
        if not check_citation(page_texts, original, c.quote).ok:
            return None
        citations.append(Citation(page=original, quote=c.quote))
    return DocumentAnswer(answer=answer.answer, citations=citations)


# ============================================================== セッション6：分割取り込み

CHUNK_PAGES = 10
CHUNK_OVERLAP = 1
IMPORT_MAX_TOKENS = 2048
IMPORT_SYSTEM = "添付のPDFはレシピ本の一部です。載っているレシピをすべて書き出してください。pageは添付PDFの中でのページ番号（1始まり）です。"
IMPORT_PROMPT = "このPDFのレシピをすべて書き出してください。"


class ChunkRecipe(BaseModel):
    id: str = Field(pattern=r"^R\d{3}$")
    name: str = Field(min_length=1)
    page: int = Field(ge=1)
    minutes: int = Field(ge=1)
    servings: int = Field(ge=1)
    kcal: int = Field(ge=0)


class ChunkRecipes(BaseModel):
    recipes: list[ChunkRecipe]


CHUNK_SCHEMA = transform_schema(ChunkRecipes)


@dataclass(frozen=True)
class ImportedRecipe:
    id: str
    name: str
    page: int
    minutes: int
    servings: int
    kcal: int


def import_total(pages: int) -> int:
    return len(chunk_ranges(pages, CHUNK_PAGES, CHUNK_OVERLAP))


async def read_chunk(llm: LLMProvider, part: bytes, start: int, end: int, used: list[Usage]) -> list[ImportedRecipe] | None:
    req = ChatRequest(
        messages=[{"role": "user", "content": [pdf_block(part), {"type": "text", "text": IMPORT_PROMPT}]}],
        system=IMPORT_SYSTEM, output_schema=CHUNK_SCHEMA, max_tokens=IMPORT_MAX_TOKENS,
    )
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)  # 上流の失敗はそのまま上げ、ジョブの失敗にする
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            parsed = ChunkRecipes.model_validate_json(result.text)
        except ValidationError:
            continue
        if any(r.page > end - start + 1 for r in parsed.recipes):
            continue
        return [ImportedRecipe(r.id, r.name, start + r.page - 1, r.minutes, r.servings, r.kcal) for r in parsed.recipes]
    return None


def merge(records: list[ImportedRecipe], pages: int) -> dict:
    by_id: dict[str, ImportedRecipe] = {}
    duplicates, conflicts = 0, set()
    for r in records:
        first = by_id.setdefault(r.id, r)
        if first is r:
            continue
        if first == r:
            duplicates += 1
        else:
            conflicts.add(r.id)
    recipes = sorted(by_id.values(), key=lambda r: (r.page, r.id))
    covered = {r.page for r in recipes}
    return {
        "recipes": recipes, "duplicates_removed": duplicates, "conflicts": sorted(conflicts),
        "missing_pages": [p for p in range(1, pages + 1) if p not in covered],
    }


async def import_recipes(llm: LLMProvider, raw: bytes, pages: int, progress: Callable[[int], None]) -> dict:
    ranges = chunk_ranges(pages, CHUNK_PAGES, CHUNK_OVERLAP)
    parts = await anyio.to_thread.run_sync(split_pdf, raw, ranges)
    records: list[ImportedRecipe] = []
    unreadable: list[int] = []
    used: list[Usage] = []
    for i, ((start, end), part) in enumerate(zip(ranges, parts, strict=True), 1):
        got = await read_chunk(llm, part, start, end, used)
        if got is None:
            unreadable.append(i)
        else:
            records.extend(got)
        progress(i)
    merged = merge(records, pages)
    return {
        "pages": pages, "chunks": len(ranges), "imported": len(merged["recipes"]),
        "duplicates_removed": merged["duplicates_removed"], "conflicts": merged["conflicts"],
        "missing_pages": merged["missing_pages"], "unreadable_chunks": unreadable,
        "needs_review": bool(merged["conflicts"] or merged["missing_pages"] or unreadable),
        "recipes": [asdict(r) for r in merged["recipes"]],
        "usage": {"input_tokens": sum(u.input_tokens for u in used), "output_tokens": sum(u.output_tokens for u in used)},
    }


class RecipeReaderFake:
    """答えを知っている Fake（セッション6）。送られた PDF を pypdf で読み、見出しの行から正しい JSON を返す。"""

    name = "recipe-reader-fake"

    def __init__(self, *, gate_at: int | None = None, gate: asyncio.Event | None = None) -> None:
        self.calls = 0
        self._gate_at, self._gate = gate_at, gate

    async def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        if self.calls == self._gate_at:
            await (self._gate or asyncio.Event()).wait()  # gate が無ければ待ち続ける（取り消しの検査用）
        texts = extract_pages(base64.b64decode(req.messages[0]["content"][0]["source"]["data"]))
        recipes = []
        for page, text in enumerate(texts, 1):
            if (h := parse_heading(text, page)) is not None:
                recipes.append({"id": h.recipe_id, "name": h.name, "page": page,
                                "minutes": h.minutes, "servings": h.servings, "kcal": h.kcal})
        text = json.dumps({"recipes": recipes}, ensure_ascii=False)
        usage = Usage(len(texts) * PDF_TOKENS_PER_PAGE, math.ceil(len(text.encode("utf-8")) / 3))
        return ChatResult(text, [], "end_turn", usage)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("取り込みは complete だけを使います")
        yield


# ============================================================== セッション7：レシートの受付と読み取り

Text40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ReceiptItem(BaseModel):
    name: Text40 = Field(description="品名（レシートの表記のまま）")
    quantity: int = Field(description="個数（書かれていなければ1）")
    price: int = Field(description="その行の金額（円の整数。個数を掛けたあとの額）")


class ReceiptRead(BaseModel):
    store: Text40 = Field(description="店名")
    purchased_at: str = Field(description="購入日（YYYY-MM-DD）")
    items: list[ReceiptItem] = Field(min_length=1, description="購入品（レシートの上から順に）")
    total: int = Field(description="合計金額（円の整数）")


RECEIPT_SCHEMA = transform_schema(ReceiptRead)
RECEIPT_PROMPT = "このレシートを読み取ってください。購入日はYYYY-MM-DDの形式、金額は円の整数で書いてください。"
RCP_MSG_INVALID_OUTPUT = "読み取り結果の形式が正しくありませんでした"
RCP_MSG_UPSTREAM = "レシートの読み取りに失敗しました。時間をおいて試してください"
MSG_DUPLICATE = "このレシートはすでに取り込み済みです"


@dataclass(frozen=True)
class Accepted:
    kind: str                                       # "image" か "pdf"
    data: bytes = field(repr=False)                 # API に送るバイト列（画像は作り直した JPEG、PDF は受け取ったまま）
    pdf_text: str = field(default="", repr=False)   # PDF から抜き出した文字（画像・文字の無い PDF は ""）


def prepare_receipt_image(raw: bytes, fmt: str) -> bytes:
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED) from None
    limit = settings.image_max_long_edge
    img.thumbnail((limit, limit))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)  # exif= を渡さないので EXIF は書き出されない
    return out.getvalue()


def accept_receipt(raw: bytes) -> Accepted:
    """中身で画像か PDF かを決め、API に送る形にそろえる。どちらでもなければ 415。"""
    fmt = sniff(raw)
    if fmt is None:
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED)
    if fmt == "PDF":
        check_pdf(raw)
        return Accepted("pdf", raw, extract_text(raw))
    return Accepted("image", prepare_receipt_image(raw, fmt))


class UpstreamUnavailable(Exception):
    """LLM の API から応答を得られなかった（SDK の再試行も尽きた）。"""


class InvalidOutput(Exception):
    """応答はあったが、読み取り結果として使える形ではなかった。usage はそこまでの全試行の合計。"""

    def __init__(self, reason: str, attempts: int, usage: Usage) -> None:
        super().__init__(reason)
        self.reason, self.attempts, self.usage = reason, attempts, usage


@dataclass(frozen=True)
class ReadResult:
    receipt: ReceiptRead
    attempts: int
    usage: Usage


def receipt_block(kind: str, data: bytes) -> dict:
    b64 = base64.standard_b64encode(data).decode("ascii")
    if kind == "image":
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    raise ValueError(f"未対応の種類です: {kind}")


def error_summary(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}" for err in e.errors()]


async def read_receipt(llm: LLMProvider, kind: str, data: bytes, max_tokens: int | None = None) -> ReadResult:
    req = ChatRequest(
        messages=[{"role": "user", "content": [receipt_block(kind, data), {"type": "text", "text": RECEIPT_PROMPT}]}],
        output_schema=RECEIPT_SCHEMA, max_tokens=max_tokens or settings.llm_max_tokens,
    )
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
            log.warning("receipt: max_tokens で打ち切られました（%d回目）", attempt)
            raise InvalidOutput("max_tokens", attempt, usage)
        try:
            return ReadResult(ReceiptRead.model_validate_json(result.text), attempt, usage)
        except ValidationError as e:
            log.warning("receipt: 検証に失敗しました（%d回目）: %s", attempt, error_summary(e))
    raise InvalidOutput("validation", MAX_ATTEMPTS, usage)


# ============================================================== セッション7：整合性検査と PDF の文字との突き合わせ

PRICE_MIN = 1
PRICE_MAX = 100_000
DATE_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MESSAGES = {
    "invalid_date": "購入日が YYYY-MM-DD の形でないか、ありえない日付（存在しない日・未来の日）です。日付を確かめてください",
    "total_mismatch": "明細の金額の合計と、合計金額が一致しません。金額を確かめてください",
    "price_out_of_range": f"金額が想定の範囲（{PRICE_MIN}〜{PRICE_MAX:,}円）を外れています。金額を確かめてください",
    "text_mismatch": "PDF に書かれた文字と読み取り結果が一致しません。レシートと見比べてください",
}


def issue(index: int | None, name: str | None, reason: str) -> dict:
    return {"index": index, "name": name, "reason": reason, "message": MESSAGES[reason]}


def valid_date(value: str, today: date) -> bool:
    if not DATE_FORMAT.match(value):
        return False
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    return day <= today


def check_receipt(read: ReceiptRead, today: date) -> list[dict]:
    """日付 → 合計 → 各行の金額の順に調べ、見つかった問題をすべて返す。"""
    issues: list[dict] = []
    if not valid_date(read.purchased_at, today):
        issues.append(issue(None, None, "invalid_date"))
    if sum(item.price for item in read.items) != read.total:
        issues.append(issue(None, None, "total_mismatch"))
    for index, item in enumerate(read.items):
        if not PRICE_MIN <= item.price <= PRICE_MAX:
            issues.append(issue(index, item.name, "price_out_of_range"))
    return issues


AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)"
YEN = re.compile(r"¥\s*" + AMOUNT)
TOTAL = re.compile(r"合計\s*¥\s*" + AMOUNT)
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def squash(text: str) -> str:
    return re.sub(r"\s+", "", nfkc(text))


def yen(value: str) -> int:
    return int(value.replace(",", ""))


@dataclass(frozen=True)
class ReceiptText:
    squashed: str
    purchased_at: str | None
    total: int | None
    amounts: frozenset[int]


def extract_text(raw: bytes) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        return ""


def parse_receipt_text(text: str) -> ReceiptText | None:
    """抜き出した文字から、突き合わせに使う値を拾う。文字が1つも無ければ None（突き合わせをしない）。"""
    t = nfkc(text)
    if not squash(t):
        return None
    day = DATE.search(t)
    total = TOTAL.search(t)
    return ReceiptText(
        squashed=squash(t),
        purchased_at=day.group(0) if day else None,
        total=yen(total.group(1)) if total else None,
        amounts=frozenset(yen(a) for a in YEN.findall(t)),
    )


def compare_with_text(read: ReceiptRead, text: ReceiptText) -> list[dict]:
    """PDF の文字と食い違う所に text_mismatch の印を付ける。日付・合計はまとめて1件、各行は1行1件。"""
    issues: list[dict] = []
    date_differs = text.purchased_at is not None and text.purchased_at != read.purchased_at
    total_differs = text.total is not None and text.total != read.total
    if date_differs or total_differs:
        issues.append(issue(None, None, "text_mismatch"))
    for index, item in enumerate(read.items):
        if squash(item.name) not in text.squashed or item.price not in text.amounts:
            issues.append(issue(index, item.name, "text_mismatch"))
    return issues
