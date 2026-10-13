"""復習3で使う部品：セッション2〜11の本文のコードから、この章で使う分を写して1つにまとめたもの。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。値と固定文は本文と同じ。
- セッション2：アップロードの受付（inspect_upload）
- セッション3：画像トークンの見積もり（estimate_image_tokens）
- セッション4：食材のモデル（Ingredient）と要確認（find_issues）
- セッション5・6：document ブロック・引用の検証・見出しの索引・選んだページの PDF・引用の番号の戻し方
- セッション7：レシートの読み取り結果（ReceiptRead）と整合性検査（check_receipt）
- セッション8：WAV の受付と 16kHz への変換（decode_wav）・表記ゆれの吸収（cer_relaxed）・検証用の音（tone_wav）
- セッション9：読み上げ用の文分割（split_sentences）・WAV の諸元（wav_info）・最初の音までの計算（plan_sentences）
- セッション10：文の組み立て（SentenceBuffer）・遅延の内訳（TurnTimes）・VAD（UtteranceDetector。セッション11の版）
- セッション11：ターンの状態機械（TurnMachine）・再生の見積もり（PlaybackEstimate）・会話履歴（Conversation）
- 共通：LLM の呼び出し回数を数える Counting と usage の合計
WebSocket の1接続を受け持つ VoiceSession（セッション11）は voice.py に写してある。
"""

from __future__ import annotations

import base64
import io
import math
import re
import unicodedata
import warnings
import wave
from bisect import bisect_right
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

import anyio
import numpy as np
import webrtcvad
from anthropic import transform_schema
from PIL import Image
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from pypdf import PdfReader, PdfWriter

from kondate.audio import wav_to_float32
from kondate.data import load_recipes
from kondate.llm import ChatRequest, ChatResult, LLMProvider, StreamEvent, Usage
from kondate.metrics import levenshtein, normalize_ja
from kondate.settings import get_settings

settings = get_settings()

# ============================================================== 共通：呼び出し回数と usage の合計


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


# ============================================================== セッション2：アップロードの受付

UPLOAD_MAX_BYTES = settings.upload_max_bytes  # 10MiB（画像・PDF・音声で共通）
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
PDF_TOKENS_PER_PAGE = 1600  # セッション5：mockllm の近似（1ページ 1600）


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

MIN_QUOTE_CHARS = 6
MAX_ATTEMPTS = 2  # 最初の1回＋再試行1回（セッション4・5・6・7で共通）
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
DOC_MSG_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_NOT_PDF = "PDF を送ってください"
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)


def pdf_block(raw: bytes) -> dict:
    data = base64.standard_b64encode(raw).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


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


# ============================================================== セッション6：見出しの索引・ページ選択

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


def select_pages(raw: bytes, pages: list[int]) -> bytes:
    reader = PdfReader(io.BytesIO(raw))
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


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


# ============================================================== セッション7：レシートの読み取り結果と整合性検査

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


# ============================================================== セッション8：WAV の受付・16kHz への変換・表記ゆれ

LOOPBACK_TEXT = "鶏むね肉とキャベツで20分で作れる料理は？"
TARGET_RATE = settings.stt_sample_rate     # 16000
MIN_SECONDS = 0.1
MAX_SECONDS = 60.0
AUDIO_UNSUPPORTED = "WAV（PCM 16bit）の音声を送ってください"


class AudioRejected(Exception):
    """受付で断る理由。HTTP のステータスとエラーの種別を持たせ、エンドポイントでそのまま返す。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def looks_like_wav(raw: bytes) -> bool:
    """先頭12バイトが RIFF....WAVE か。ファイル名や Content-Type ではなく中身の目印を見る。"""
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"


def lowpass(audio: np.ndarray, rate: int, cutoff_hz: float, taps: int = 101) -> np.ndarray:
    """cutoff_hz より高い音を弱める（窓付き sinc の FIR フィルタ）。間引く前にかけて折り返し雑音を防ぐ。"""
    n = np.arange(taps) - (taps - 1) / 2
    fc = cutoff_hz / rate
    h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
    h /= h.sum()
    half = (taps - 1) // 2
    return np.convolve(audio, h)[half:half + len(audio)].astype(np.float32)


def to_16k_mono(audio: np.ndarray, rate: int, target: int = TARGET_RATE) -> np.ndarray:
    """モノラルの float32 配列のサンプリングレートを target に変える。サンプル数は round(元の数 × target ÷ rate)。"""
    if rate == target:
        return audio.astype(np.float32, copy=False)
    if rate > target:
        audio = lowpass(audio, rate, cutoff_hz=target / 2 * 0.9)
    n_out = round(len(audio) * target / rate)
    t_in = np.arange(len(audio)) / rate
    t_out = np.arange(n_out) / target
    return np.interp(t_out, t_in, audio).astype(np.float32)


def decode_wav(raw: bytes) -> np.ndarray:
    """WAV のバイト列 → 16kHz モノラルの float32 配列。受け付けられなければ AudioRejected。"""
    if not looks_like_wav(raw):
        raise AudioRejected(415, "unsupported_media", AUDIO_UNSUPPORTED)
    try:
        audio, rate = wav_to_float32(raw)       # PCM 16bit 以外は ValueError。ステレオは左右を平均してモノラルにする
    except (wave.Error, EOFError, ValueError):
        raise AudioRejected(415, "unsupported_media", AUDIO_UNSUPPORTED) from None
    if rate <= 0:
        raise AudioRejected(415, "unsupported_media", AUDIO_UNSUPPORTED)
    seconds = len(audio) / rate
    if seconds > MAX_SECONDS:
        raise AudioRejected(413, "too_large", f"音声は {MAX_SECONDS:.0f} 秒以下にしてください")
    if seconds < MIN_SECONDS:
        raise AudioRejected(422, "invalid_request", f"入力値が正しくありません：audio（{MIN_SECONDS} 秒以上の音声を送ってください）")
    return to_16k_mono(audio, rate)


_KATA_TO_HIRA = {code: code - 0x60 for code in range(ord("ァ"), ord("ヶ") + 1)}
VARIANTS = {
    "胸肉": "むね肉",
    "人参": "にんじん",
    "ご飯": "ごはん",
}


def fold_kana(text: str) -> str:
    """カタカナをひらがなにする（ニンジン → にんじん）。長音「ー」と中黒「・」はそのまま。"""
    return text.translate(_KATA_TO_HIRA)


def normalize_relaxed(text: str) -> str:
    out = fold_kana(normalize_ja(text))
    for src, dst in VARIANTS.items():
        out = out.replace(src, dst)
    return out


def cer_relaxed(reference: str, hypothesis: str) -> float:
    """表記ゆれを吸収した CER。読み違い（晩ごはん → 番模範）は吸収しない。"""
    ref, hyp = normalize_relaxed(reference), normalize_relaxed(hypothesis)
    return levenshtein(ref, hyp) / max(1, len(ref))


def tone(freq: float, rate: int, seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(round(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def tone_wav(rate: int, seconds: float, *, channels: int = 1, sampwidth: int = 2, freq: float = 440.0) -> bytes:
    """検証用の合成音（サイン波）の WAV。録音を使わず、長さ・レート・チャンネル・ビット深度を決めて作れる。"""
    mono = tone(freq, rate, seconds)
    if sampwidth == 2:
        samples = (mono * 32767).astype("<i2")
    else:  # 8bit の WAV は符号なし（0〜255）
        samples = ((mono + 1.0) * 127.5).astype(np.uint8)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(np.repeat(samples, channels).tobytes())
    return buf.getvalue()


# ============================================================== セッション9：文分割・WAV の諸元・最初の音までの計算

_FENCE = re.compile(r"^\s*```")
_HEAD = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"\*\*|__|~~|[*`]")
_RULE = re.compile(r"(?:[-*_]\s*){3,}")
_SENTENCE = re.compile(r"[^。？！]+[。？！]*")
_SPEAKABLE = re.compile(r"[^\W_]")
VOICE_CREDIT = settings.voicevox_credit    # 「VOICEVOX:ずんだもん」


def strip_markdown(line: str) -> str:
    """1行から Markdown の記号を除き、読み上げる文字だけにする。"""
    if _FENCE.match(line):
        return ""
    line = _HEAD.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = _EMPHASIS.sub("", line).replace("|", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return "" if _RULE.fullmatch(line) else line


def split_sentences(text: str) -> list[str]:
    """Markdown の返答を、読み上げる文のリストにする（順番は元のまま）。"""
    sentences: list[str] = []
    for line in text.splitlines():
        for piece in _SENTENCE.findall(strip_markdown(line)):
            piece = piece.strip()
            if _SPEAKABLE.search(piece):
                sentences.append(piece)
    return sentences


def wav_info(wav: bytes) -> tuple[int, int, int, int]:
    """(サンプリングレート, チャンネル数, 1サンプルのバイト数, 1チャンネルあたりのサンプル数)。"""
    with wave.open(io.BytesIO(wav)) as wf:
        return wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()


@dataclass(frozen=True)
class Timeline:
    first_audio: float           # 最初の音が鳴り始める時刻（秒）
    gaps: tuple[float, ...]      # 文と文の間で、再生が止まって待った時間（秒）
    finished: float              # 最後の音が鳴り終わる時刻（秒）


def plan_whole(synth_seconds: float, audio_seconds: float) -> Timeline:
    """全文をまとめて合成してから再生する。"""
    return Timeline(round(synth_seconds, 3), (), round(synth_seconds + audio_seconds, 3))


def plan_sentences(synth: list[float], audio: list[float]) -> Timeline:
    """文ごとに合成し、できた順に再生する。synth[i] は i 文目の合成時間、audio[i] はその音声の長さ。"""
    ready = play_end = 0.0
    first = 0.0
    gaps: list[float] = []
    for i, (s, a) in enumerate(zip(synth, audio, strict=True)):
        ready += s
        start = max(ready, play_end)
        if i == 0:
            first = start
        else:
            gaps.append(round(start - play_end, 3))
        play_end = start + a
    return Timeline(round(first, 3), tuple(gaps), round(play_end, 3))


# ============================================================== セッション10：文の組み立て・遅延の内訳・VAD


class SentenceBuffer:
    """LLM の差分（ストリーミング）を受け取り、読み上げる文が完成するたびに返す。"""

    def __init__(self) -> None:
        self._line = ""        # まだ改行が来ていない行（書きかけの行）
        self._sent = 0         # その行から、すでに返した文の数

    def feed(self, delta: str) -> list[str]:
        """差分を足し、新しく完成した文を返す（無ければ空のリスト）。"""
        self._line += delta
        done: list[str] = []
        while "\n" in self._line:
            line, self._line = self._line.split("\n", 1)
            done += split_sentences(line)[self._sent:]
            self._sent = 0
        pieces = split_sentences(self._line)
        ready = len(pieces) - 1
        if ready > self._sent:
            done += pieces[self._sent:ready]
            self._sent = ready
        return done

    def flush(self) -> list[str]:
        """返答が終わったときに呼び、残りの文を返す。"""
        rest = split_sentences(self._line)[self._sent:]
        self._line, self._sent = "", 0
        return rest


KEYS = ("vad", "stt", "llm_first_sentence", "tts_first", "first_audio")


@dataclass
class TurnTimes:
    last_voice: float
    speech_end: float
    transcript: float | None = None
    first_sentence: float | None = None
    tts_first: float | None = None
    first_audio: float | None = None

    def sentence_ready(self, now: float) -> None:
        """文が完成するたびに呼ぶ。記録するのは最初の1回だけ。"""
        if self.first_sentence is None:
            self.first_sentence = now

    def latency_ms(self) -> dict[str, int | None]:
        """ミリ秒の整数に丸めた内訳。返答しなかったターンでは後ろの3つが None。"""

        def ms(start: float | None, end: float | None) -> int | None:
            return None if start is None or end is None else round((end - start) * 1000)

        return {
            "vad": ms(self.last_voice, self.speech_end),
            "stt": ms(self.speech_end, self.transcript),
            "llm_first_sentence": ms(self.transcript, self.first_sentence),
            "tts_first": ms(self.first_sentence, self.tts_first),
            "first_audio": ms(self.last_voice, self.first_audio),
        }


SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2     # 960 バイト（480 サンプル × 2 バイト）
AGGRESSIVENESS = 2
START_MS = 150
END_SILENCE_MS = 600
PREROLL_MS = 300
MAX_UTTERANCE_MS = 15000


@dataclass(frozen=True)
class VadEvent:
    kind: str                  # "speech_start" か "speech_end"
    frame: int                 # 判定したフレームの番号（0 から数える。1つ 30ms）
    audio: bytes = b""         # speech_end のときだけ、1発話ぶんの PCM 16bit


class UtteranceDetector:
    def __init__(
        self,
        is_speech: Callable[[bytes], bool] | None = None,
        *,
        start_ms: int = START_MS,
        end_silence_ms: int = END_SILENCE_MS,
        preroll_ms: int = PREROLL_MS,
        max_ms: int = MAX_UTTERANCE_MS,
    ) -> None:
        if is_speech is None:
            vad = webrtcvad.Vad(AGGRESSIVENESS)

            def is_speech(frame: bytes) -> bool:
                return vad.is_speech(frame, SAMPLE_RATE)

        self._is_speech = is_speech
        self.start_frames = start_ms // FRAME_MS
        self.end_frames = end_silence_ms // FRAME_MS
        self.max_frames = max_ms // FRAME_MS
        self._pre: deque[bytes] = deque(maxlen=preroll_ms // FRAME_MS + self.start_frames)
        self.frame_index = -1
        self.last_voiced_frame = -1
        self.reset()

    def reset(self) -> None:
        """溜めた音と状態を捨て、話し始めを待つ状態に戻す（フレームの番号は続きから数える）。"""
        self._buf = b""
        self._pre.clear()
        self._utt: list[bytes] = []
        self.in_speech = False
        self._voiced_run = 0
        self._silent_run = 0
        self.voiced_frames = 0         # この発話の中の「声あり」フレームの数（セッション11で追加）

    def push(self, pcm: bytes) -> list[VadEvent]:
        """届いた PCM を足し、30ms のフレームがそろうたびに判定する。起きたイベントを返す。"""
        self._buf += pcm
        events: list[VadEvent] = []
        while len(self._buf) >= FRAME_BYTES:
            frame, self._buf = self._buf[:FRAME_BYTES], self._buf[FRAME_BYTES:]
            event = self._step(frame)
            if event is not None:
                events.append(event)
        return events

    def _step(self, frame: bytes) -> VadEvent | None:
        self.frame_index += 1
        voiced = self._is_speech(frame)
        if voiced:
            self.last_voiced_frame = self.frame_index
        if not self.in_speech:
            self._pre.append(frame)
            self._voiced_run = self._voiced_run + 1 if voiced else 0
            if self._voiced_run < self.start_frames:
                return None
            self.in_speech, self._silent_run = True, 0
            self.voiced_frames = self._voiced_run
            self._utt = list(self._pre)
            self._pre.clear()
            return VadEvent("speech_start", self.frame_index)
        self._utt.append(frame)
        if voiced:
            self.voiced_frames += 1
        self._silent_run = 0 if voiced else self._silent_run + 1
        if self._silent_run < self.end_frames and len(self._utt) < self.max_frames:
            return None
        audio = b"".join(self._utt)
        self._utt, self.in_speech, self._voiced_run = [], False, 0
        return VadEvent("speech_end", self.frame_index, audio)


# ============================================================== セッション11：状態機械・再生の見積もり・会話履歴


class TurnState(StrEnum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


ALLOWED = {
    (TurnState.LISTENING, TurnState.THINKING),
    (TurnState.THINKING, TurnState.SPEAKING),
    (TurnState.THINKING, TurnState.LISTENING),
    (TurnState.SPEAKING, TurnState.LISTENING),
}


class TurnMachine:
    def __init__(self) -> None:
        self.state = TurnState.LISTENING
        self.log: list[tuple[str, str]] = [(self.state.value, "connect")]   # (移った先, 理由) の記録

    def to(self, new: TurnState, reason: str) -> None:
        if (self.state, new) not in ALLOWED:
            raise ValueError(f"{self.state} から {new} へは移れません（{reason}）")
        self.state = new
        self.log.append((new.value, reason))


PLAYBACK_LEAD_S = 0.3


class PlaybackEstimate:
    def __init__(self, lead_s: float = PLAYBACK_LEAD_S) -> None:
        self.lead_s = lead_s
        self.texts: list[str] = []
        self.starts: list[float] = []
        self.ends: list[float] = []

    def add(self, text: str, seconds: float, sent_at: float) -> None:
        """WAV を1つ送り終えたときに呼ぶ。"""
        start = sent_at + self.lead_s
        if self.ends:
            start = max(start, self.ends[-1])
        self.texts.append(text)
        self.starts.append(start)
        self.ends.append(start + seconds)

    def heard_count(self, now: float) -> int:
        """now までに鳴り終えた（と見積もった）文の数。＝ まだ鳴り終えていない最初の文の番号。"""
        return bisect_right(self.ends, now)

    def heard(self, now: float) -> list[str]:
        return self.texts[:self.heard_count(now)]

    def finished(self, now: float) -> bool:
        """送った音声を、すべて鳴らし終えたか（1つも送っていなければ True）。"""
        return self.heard_count(now) == len(self.ends)


INTERRUPTED_NOTE = "（ここでユーザーが話し始めたため、読み上げを止めました。この先は伝わっていません）"


class Conversation:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1] = {"role": "user", "content": self.messages[-1]["content"] + "\n" + text}
        else:
            self.messages.append({"role": "user", "content": text})

    def add_assistant(self, sentences: list[str], *, interrupted: bool) -> None:
        lines = list(sentences)
        if interrupted:
            lines.append(INTERRUPTED_NOTE)
        if lines:
            self.messages.append({"role": "assistant", "content": "\n".join(lines)})

    def snapshot(self) -> list[dict]:
        """LLM に渡す写し（渡したあとに履歴が伸びても、渡した中身は変わらない）。"""
        return [dict(m) for m in self.messages]
