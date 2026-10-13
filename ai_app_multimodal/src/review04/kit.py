"""復習4で使う部品：セッション2〜14の本文のコードから、この章で使う分だけを1つにまとめて写したもの。

セッションのコードは他のセッションを import しない決まりなので、必要な分だけ写してある。値と固定文は本文と同じ。
- セッション3：画像トークンの見積もり（estimate_image_tokens）と、長辺をそろえる縮小の寸法（fit_long_edge）
- セッション4・14：画像の受付と前処理（accept_image）・食材のモデル（FridgeScan）・読み取りと再試行（scan_fridge）
- セッション5・6：ask の system（SYSTEM_PROMPT）と、PDF 1ページあたりのトークン
- セッション7：レシートの読み取り結果のモデル（ReceiptRead）と指示文
- セッション8・12：表記ゆれをそろえる正規化（normalize_relaxed）
- セッション9：読み上げ用の文分割（split_sentences）
- セッション11：ターンの状態機械（TurnMachine）
- セッション12：正解データとの照合（score_case・summarize）と回帰の判定（find_regressions）
- セッション13：保持期限つきの台帳（PersonalStore）・付帯情報の検査（image_findings）・ログのマスク（MaskFilter）
- セッション14：キャッシュキーと応答キャッシュ・利用量の帳簿（UsageBook）・CPU を食う処理の入口（CpuGate）・単価表
- 共通：usage の合計（sum_usage）・テキストのトークン（text_tokens）・呼び出し回数を数える Counting
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import re
import warnings
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, TypeVar

import anyio
import yaml
from anthropic import transform_schema
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from kondate.clock import Clock
from kondate.llm import ChatRequest, ChatResult, LLMProvider, StreamEvent, Usage
from kondate.metrics import normalize_ja
from kondate.settings import get_settings
from kondate.usage import UsageLog

settings = get_settings()
T = TypeVar("T")

# ============================================================== 共通

FRAME_TOKENS = 4 + 3  # リクエスト1件の 4 ＋ メッセージ1件の 3（mockllm の式）


def text_tokens(text: str) -> int:
    """mockllm の式：UTF-8 のバイト数を3で割って切り上げ。"""
    return math.ceil(len(text.encode("utf-8")) / 3)


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


def fit_long_edge(width: int, height: int, limit: int) -> tuple[int, int]:
    """長辺が limit に収まるよう縦横比を保って縮めた寸法（拡大はしない）。前処理の thumbnail と同じ比率。"""
    if max(width, height) <= limit:
        return width, height
    scale = limit / max(width, height)
    return round(width * scale), round(height * scale)


# ============================================================== セッション4・14：画像の受付・前処理・読み取り

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)  # 上限ちょうどで止める（セッション2）

IMAGE_MAGIC = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
]
MSG_TOO_MANY_PIXELS = "画像の画素数が大きすぎます（4000万画素まで）"
MSG_UNSUPPORTED_IMAGE = "JPEG・PNG・WebP・GIF の画像を送ってください"


class Rejected(Exception):
    """受け付けられないファイル。status・type・message は利用者にそのまま返す固定の値。"""

    def __init__(self, status: int, type_: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.message = status, type_, message


def sniff_image(raw: bytes) -> str | None:
    for magic, fmt in IMAGE_MAGIC:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    return None


@dataclass(frozen=True)
class PreparedImage:
    data: bytes = field(repr=False)
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
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED_IMAGE)
    try:
        with Image.open(io.BytesIO(raw), formats=[fmt]) as img:
            had_exif = len(img.getexif()) > 0
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(413, "too_large", MSG_TOO_MANY_PIXELS) from None
    except (OSError, ValueError, SyntaxError):
        raise Rejected(415, "unsupported_media", MSG_UNSUPPORTED_IMAGE) from None
    original = img.size
    img.thumbnail((max_long_edge, max_long_edge))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)  # exif= を渡さないので EXIF は書き出されない
    return PreparedImage(out.getvalue(), "image/jpeg", original, img.size, had_exif)


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
MAX_ATTEMPTS = 2  # 最初の1回＋再試行1回（セッション4〜7で共通）


async def scan_fridge(llm: LLMProvider, jpeg: bytes, used: list[Usage]) -> FridgeScan | None:
    """形が正しくなければ1回だけ再試行する（セッション4）。使ったトークンは used に足していく（セッション14）。"""
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(jpeg).decode("ascii")}}
    req = ChatRequest(messages=[{"role": "user", "content": [image, {"type": "text", "text": FRIDGE_PROMPT}]}],
                      output_schema=FRIDGE_SCHEMA, max_tokens=settings.llm_max_tokens)
    for _ in range(MAX_ATTEMPTS):
        result = await llm.complete(req)  # 上流のエラーはそのまま上げる
        used.append(result.usage)
        if result.stop_reason == "max_tokens":
            return None
        try:
            return FridgeScan.model_validate_json(result.text)
        except ValidationError:
            continue
    return None


# ============================================================== セッション5・6：ask の system と PDF のトークン

PDF_TOKENS_PER_PAGE = 1600  # mockllm の近似
SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)


# ============================================================== セッション7：レシートの読み取り結果

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
MSG_DUPLICATE = "このレシートはすでに取り込み済みです"


# ============================================================== セッション8・12：表記ゆれをそろえる正規化

_KATA_TO_HIRA = {code: code - 0x60 for code in range(ord("ァ"), ord("ヶ") + 1)}
VARIANTS = {"胸肉": "むね肉", "人参": "にんじん", "ご飯": "ごはん"}


def normalize_relaxed(text: str) -> str:
    out = normalize_ja(text).translate(_KATA_TO_HIRA)
    for src, dst in VARIANTS.items():
        out = out.replace(src, dst)
    return out


# ============================================================== セッション9：読み上げ用の文分割

_FENCE = re.compile(r"^\s*```")
_HEAD = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"\*\*|__|~~|[*`]")
_RULE = re.compile(r"(?:[-*_]\s*){3,}")
_SENTENCE = re.compile(r"[^。？！]+[。？！]*")
_SPEAKABLE = re.compile(r"[^\W_]")


def strip_markdown(line: str) -> str:
    if _FENCE.match(line):
        return ""
    line = _HEAD.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = _EMPHASIS.sub("", line).replace("|", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return "" if _RULE.fullmatch(line) else line


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for line in text.splitlines():
        for piece in _SENTENCE.findall(strip_markdown(line)):
            piece = piece.strip()
            if _SPEAKABLE.search(piece):
                sentences.append(piece)
    return sentences


# ============================================================== セッション11：ターンの状態機械

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


# ============================================================== セッション12：照合と回帰の判定

AMOUNT_REL_TOL = 0.10


@dataclass(frozen=True)
class Gold:
    media: str
    items: tuple[dict, ...]   # 1件ずつの {name, …}。値が None の項目は採点しない
    header: dict              # 全体の項目（レシートの店名・購入日・合計）


def norm_name(text: str) -> str:
    return normalize_relaxed(text)


FIELD_RULES: dict[str, Callable[[object, object], bool]] = {
    "amount": lambda p, g: abs(p - g) <= AMOUNT_REL_TOL * g,
    "quantity": lambda p, g: p == g,
    "price": lambda p, g: p == g,
    "total": lambda p, g: p == g,
    "purchased_at": lambda p, g: p == g,
    "store": lambda p, g: norm_name(p) == norm_name(g),
}


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    predicted: int
    gold: int
    matched: int
    fields_checked: int
    fields_correct: int
    errors: tuple[str, ...]

    @property
    def exact(self) -> bool:
        return self.predicted == self.gold == self.matched and self.fields_checked == self.fields_correct


def _fmt(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def score_case(case_id: str, gold: Gold, pred: dict) -> CaseScore:
    """pred は {"items": [{name, …}], "header": {…}}。誤りは「全体の項目 → 品目の項目 → 余計 → 見逃し」の順。"""
    errors: list[str] = []
    checked = correct = 0

    def judge(label: str, name: str, p: object, g: object) -> None:
        nonlocal checked, correct
        if g is None:
            return
        checked += 1
        if p is not None and FIELD_RULES[name](p, g):
            correct += 1
        else:
            errors.append(f"{label}{name}：{_fmt(p)} ≠ {_fmt(g)}")

    for name, g in gold.header.items():
        judge("", name, pred["header"].get(name), g)

    free = list(range(len(gold.items)))
    extra: list[str] = []
    for p_item in pred["items"]:
        key = norm_name(p_item["name"])
        hit = next((i for i in free if norm_name(gold.items[i]["name"]) == key), None)
        if hit is None:
            extra.append(p_item["name"])
            continue
        free.remove(hit)
        g_item = gold.items[hit]
        for name, g in g_item.items():
            if name != "name":
                judge(f"{g_item['name']} の ", name, p_item.get(name), g)
    errors += [f"余計：{name}" for name in extra]
    errors += [f"見逃し：{gold.items[i]['name']}" for i in free]
    matched = len(gold.items) - len(free)
    return CaseScore(case_id, len(pred["items"]), len(gold.items), matched, checked, correct, tuple(errors))


def ratio(num: int, den: int) -> float:
    """分母が0なら 1.0（予測が0件なら「間違いも言っていない」。そのとき見逃しは再現率に出る）。"""
    return round(num / den, 4) if den else 1.0


def summarize(scores: Iterable[CaseScore]) -> dict:
    scores = list(scores)
    tp = sum(s.matched for s in scores)
    return {
        "cases": len(scores),
        "precision": ratio(tp, sum(s.predicted for s in scores)),
        "recall": ratio(tp, sum(s.gold for s in scores)),
        "field_accuracy": ratio(sum(s.fields_correct for s in scores), sum(s.fields_checked for s in scores)),
        "exact_match_rate": ratio(sum(s.exact for s in scores), len(scores)),
    }


@dataclass(frozen=True)
class Rule:
    better: str                  # "higher"（大きいほど良い）か "lower"（小さいほど良い）
    tolerance: float             # 基準からこの幅を超えて悪くなったら回帰
    limit: float | None = None   # 基準に関係なく、これより悪ければ失敗


RULES = {
    "extraction.precision": Rule("higher", 0.0),
    "extraction.recall": Rule("higher", 0.0),
    "extraction.field_accuracy": Rule("higher", 0.0),
    "extraction.exact_match_rate": Rule("higher", 0.0),
    "cer.weighted_strict": Rule("lower", 0.01, limit=0.15),
    "cer.weighted_relaxed": Rule("lower", 0.01, limit=0.15),
}


def find_regressions(current: dict, baseline: dict, rules: dict[str, Rule] = RULES) -> list[str]:
    now, before = current["deterministic"], baseline["deterministic"]
    found = []
    for key, rule in rules.items():
        if key not in now:
            found.append(f"{key}：今回の結果にありません")
            continue
        value = now[key]
        sign = 1 if rule.better == "higher" else -1
        if rule.limit is not None and sign * (value - rule.limit) < 0:
            word = "下限 {} を下回りました" if rule.better == "higher" else "上限 {} を超えました"
            found.append(f"{key}：{value} が{word.format(rule.limit)}")
        old = before.get(key)
        if old is not None and round(sign * (value - old), 6) < -rule.tolerance:
            found.append(f"{key}：{old} → {value}（悪化。許容幅 {rule.tolerance}）")
    return found


# ============================================================== セッション13：保持期限つきの台帳と付帯情報

RETENTION = {
    "upload": timedelta(hours=24),
    "document": timedelta(days=30),
    "receipt": timedelta(days=30),
    "voice": timedelta(days=7),
}
KEYS = {"upload": "uploads", "document": "documents", "receipt": "receipts", "voice": "voice"}

MAKE, MODEL, DATETIME = 0x010F, 0x0110, 0x0132
EXIF_IFD, GPS_IFD, DATETIME_ORIGINAL = 0x8769, 0x8825, 0x9003


def image_findings(raw: bytes) -> dict[str, bool]:
    """画像の EXIF に、位置・機種・撮影日時が入っているか。"""
    with Image.open(io.BytesIO(raw)) as img:
        exif = img.getexif()
        return {
            "exif": len(exif) > 0,
            "gps": len(exif.get_ifd(GPS_IFD)) > 0,
            "device": MAKE in exif or MODEL in exif,
            "taken_at": DATETIME in exif or DATETIME_ORIGINAL in exif.get_ifd(EXIF_IFD),
        }


@dataclass
class Held:
    kind: str
    item_id: str
    user_id: str
    expires_at: datetime
    path: Path | None = None
    data: object = field(default=None, repr=False)


class PersonalStore:
    """利用者の個人データの台帳（メモリに持つ簡易版）。"""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._items: dict[str, Held] = {}

    def add(self, kind: str, item_id: str, user_id: str, *, path: Path | None = None, data: object = None) -> Held:
        held = Held(kind, item_id, user_id, self.clock.now() + RETENTION[kind], path, data)
        self._items[item_id] = held
        return held

    def get(self, user_id: str, item_id: str) -> Held | None:
        held = self._items.get(item_id)
        if held is None or held.user_id != user_id or self.clock.now() >= held.expires_at:
            return None
        return held

    def of_user(self, user_id: str) -> list[Held]:
        return [h for h in self._items.values() if h.user_id == user_id]

    def sweep(self) -> dict[str, int]:
        now = self.clock.now()
        return self._remove(lambda held: now >= held.expires_at)

    def delete_user(self, user_id: str) -> dict[str, int]:
        return self._remove(lambda held: held.user_id == user_id)

    def _remove(self, match: Callable[[Held], bool]) -> dict[str, int]:
        removed = dict.fromkeys(KEYS.values(), 0)
        for held in [h for h in self._items.values() if match(h)]:
            if held.path is not None:
                held.path.unlink(missing_ok=True)
            del self._items[held.item_id]
            removed[KEYS[held.kind]] += 1
        return removed


def forget_usage(usage: UsageLog, user_id: str) -> int:
    """利用記録から、その利用者の行を消して件数を返す（セッション13の DELETE /api/me/data）。"""
    before = len(usage.records)
    usage.records[:] = [r for r in usage.records if r.user_id != user_id]
    return before - len(usage.records)


# ============================================================== セッション13：ログのマスク

SAFE_KEYS = frozenset({
    "user_id", "request_id", "upload_id", "document_id", "receipt_id", "voice_id",
    "kind", "bytes", "chars", "pages", "audio_seconds", "sha12", "store_audio", "error",
    "uploads", "documents", "receipts", "voice", "usage",
})
LOG_FORMAT = "%(levelname)s %(name)s %(message)s%(fields_text)s"


def sha12(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return hashlib.sha256(raw).hexdigest()[:12]


def fold(value: object) -> object:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes len={len(value)} sha={sha12(bytes(value))}>"
    if isinstance(value, str):
        return f"<text chars={len(value)} sha={sha12(value)}>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def keep(key: str, value: object) -> bool:
    return key in SAFE_KEYS and (value is None or isinstance(value, (str, bool, int, float)))


class MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "masked", False):
            return True
        fields = dict(getattr(record, "fields", None) or {})
        masked = {k: v if keep(k, v) else fold(v) for k, v in fields.items()}
        if record.args:
            args = record.args
            record.args = {k: fold(v) for k, v in args.items()} if isinstance(args, dict) else tuple(map(fold, args))
        if record.exc_info:
            masked["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "unknown"
            record.exc_info, record.exc_text = None, None
        record.fields = masked
        record.fields_text = "".join(f" {k}={v}" for k, v in masked.items())
        record.masked = True
        return True


def masked_handler(handler: logging.Handler | None = None) -> logging.Handler:
    handler = handler or logging.StreamHandler()
    handler.addFilter(MaskFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


# ============================================================== セッション14：キャッシュキーと応答キャッシュ

KEY_VERSION = 1


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def cache_key(*, scope: str, kind: str, content_sha256: str, preprocess: dict,
              prompt: str, system: str | None, model: str, schema: dict | None) -> str:
    material = {
        "v": KEY_VERSION, "scope": scope, "kind": kind, "content_sha256": content_sha256,
        "preprocess": preprocess, "prompt": prompt, "system": system, "model": model,
        "schema_sha256": sha256_hex(canonical(schema)) if schema is not None else None,
    }
    return sha256_hex(canonical(material))


@dataclass(frozen=True)
class Entry:
    scope: str
    value: dict
    usage: Usage
    stored_at: datetime


class ResponseCache:
    """プロセス内メモリの応答キャッシュ。件数の上限（古いものから追い出す）と保持時間を持つ。"""

    def __init__(self, clock: Clock, max_entries: int = 256, ttl_seconds: int = 24 * 3600) -> None:
        self._clock = clock
        self.max_entries = max_entries
        self.ttl = timedelta(seconds=ttl_seconds)
        self._entries: OrderedDict[str, Entry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> Entry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock.now() - entry.stored_at >= self.ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry

    def put(self, key: str, scope: str, value: dict, usage: Usage) -> None:
        self._entries[key] = Entry(scope, value, usage, self._clock.now())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def forget(self, scope: str) -> int:
        keys = [k for k, e in self._entries.items() if e.scope == scope]
        for k in keys:
            del self._entries[k]
        return len(keys)


# ============================================================== セッション14：利用量の帳簿

ZERO_CACHE_TOKENS = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
ZERO_LOOKUPS = {"hits": 0, "misses": 0}


class UsageBook:
    def __init__(self, log: UsageLog) -> None:
        self.log = log
        self._cache_tokens: dict[str, dict[str, int]] = {}
        self._lookups: dict[str, dict[str, int]] = {}

    def add_llm(self, user_id: str, model: str, usage: Usage, request_id: str | None = None) -> None:
        self.log.add(user_id, "llm", model, input_tokens=usage.input_tokens,
                     output_tokens=usage.output_tokens, request_id=request_id)
        c = self._cache_tokens.setdefault(user_id, dict(ZERO_CACHE_TOKENS))
        c["cache_creation_input_tokens"] += usage.cache_creation_input_tokens
        c["cache_read_input_tokens"] += usage.cache_read_input_tokens

    def count_lookup(self, user_id: str, hit: bool) -> None:
        c = self._lookups.setdefault(user_id, dict(ZERO_LOOKUPS))
        c["hits" if hit else "misses"] += 1

    def summary(self, user_id: str) -> dict:
        mine = [r for r in self.log.records if r.user_id == user_id]

        def tokens(name: str) -> int:
            return sum(getattr(r, name) for r in mine if r.kind == "llm")

        def seconds(kind: str, name: str) -> float:
            return round(sum((getattr(r, name) for r in mine if r.kind == kind), 0.0), 3)

        return {
            "llm": {"input_tokens": tokens("input_tokens"), "output_tokens": tokens("output_tokens"),
                    **self._cache_tokens.get(user_id, ZERO_CACHE_TOKENS)},
            "stt_seconds": seconds("stt", "audio_seconds"),
            "tts_seconds": seconds("tts", "audio_seconds"),
            "stt_processing_seconds": seconds("stt", "processing_seconds"),
            "tts_processing_seconds": seconds("tts", "processing_seconds"),
            "response_cache": dict(self._lookups.get(user_id, ZERO_LOOKUPS)),
        }


# ============================================================== セッション14：CPU を食う処理の入口

class Busy(Exception):
    """待ち行列があふれた。どの入口か（stt / tts）だけを持つ。"""

    def __init__(self, gate: str) -> None:
        super().__init__(gate)
        self.gate = gate


class CpuGate:
    """同時実行数と待ち行列の上限。「動いている数＋待っている数」が上限に達していたら Busy。"""

    def __init__(self, name: str, concurrency: int, max_waiting: int) -> None:
        self.name, self.concurrency, self.max_waiting = name, concurrency, max_waiting
        self.limiter = anyio.CapacityLimiter(concurrency)
        self.inflight = 0
        self.rejected = 0

    def _admit(self) -> None:
        if self.inflight >= self.concurrency + self.max_waiting:
            self.rejected += 1
            raise Busy(self.name)
        self.inflight += 1

    async def run_sync(self, fn: Callable[..., T], *args: Any) -> T:
        self._admit()
        try:
            return await anyio.to_thread.run_sync(fn, *args, limiter=self.limiter)
        finally:
            self.inflight -= 1

    async def run(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        self._admit()
        try:
            async with self.limiter:
                return await fn(*args, **kwargs)
        finally:
            self.inflight -= 1


# ============================================================== セッション14：単価表

PRICING = Path(__file__).with_name("pricing.yaml")
MTOK = Decimal(1_000_000)
CENT = Decimal("0.01")


def to_decimal(obj):
    if isinstance(obj, dict):
        return {k: to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return Decimal(str(obj))
    return obj


def load_pricing(path: Path = PRICING) -> dict:
    return to_decimal(yaml.safe_load(path.read_text(encoding="utf-8")))


def round_cost(value: Decimal) -> Decimal:
    """表示用に小数第2位で四捨五入する（単位は単価表の currency）。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)
