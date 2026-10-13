"""復習3の入力を作る。どれも検証用メディア・mockllm の固定応答・決まった式から作る（実写・著作物・録音は使わない）。"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image

from kondate.media import media_path
from src.review03.kit import VOICE_CREDIT, Ingredient, ReceiptRead

ROOT = Path(__file__).resolve().parents[2]


def receipt_png() -> bytes:
    """600×900 の PNG。"""
    return media_path("receipt.png").read_bytes()


def receipt_pdf() -> bytes:
    """1ページの PDF（文字のデータあり）。"""
    return media_path("receipt.pdf").read_bytes()


def fridge_jpg() -> bytes:
    """1280×960 の JPEG（ダミーの EXIF・位置情報（GPS）入り）。"""
    return media_path("fridge.jpg").read_bytes()


def plain_jpeg(width: int, height: int) -> bytes:
    """無地の JPEG（寸法だけを決めた画像）。"""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


@lru_cache
def recipe_book_full() -> bytes:
    """120ページの PDF（R001〜R120 が1ページに1件ずつ）。"""
    return media_path("recipe_book_full.pdf").read_bytes()


@lru_cache
def kondate_reply() -> str:
    """mockllm の kondate_chat が返す返答（Markdown の番号付きリストを含む5文）。"""
    data = json.loads((ROOT / "mockllm/fixtures/kondate_chat.json").read_text(encoding="utf-8"))
    return data["steps"][0]["text"]


# mockllm の receipt シナリオが返す読み取り結果（receipt.png・receipt.pdf に書かれた内容どおり）
GOOD = {
    "store": "こんだてマート",
    "purchased_at": "2026-10-01",
    "items": [
        {"name": "鶏むね肉", "quantity": 1, "price": 398},
        {"name": "キャベツ", "quantity": 1, "price": 198},
        {"name": "卵（10個入り）", "quantity": 1, "price": 248},
        {"name": "牛乳", "quantity": 1, "price": 228},
    ],
    "total": 1072,
}


def receipt_read(**over) -> ReceiptRead:
    """GOOD の一部だけを変えた読み取り結果。"""
    return ReceiptRead.model_validate({**GOOD, **over})


def fridge_items() -> list[Ingredient]:
    """冷蔵庫の写真から読み取った、という想定の食材3件（セッション4の要確認の例）。"""
    def ing(name: str, confidence: float) -> Ingredient:
        return Ingredient(name=name, quantity="1個", amount=1, unit="個", confidence=confidence, category="野菜")
    return [ing("キャベツ", 0.94), ing("鶏ムネ肉", 0.9), ing("にんじん", 0.42)]


# ---- 問題5：WebSocket の下りメッセージの記録 ----

WAV_BYTES = 100
LATENCY = {"vad": 600, "stt": 1650, "llm_first_sentence": 50, "tts_first": 3400, "first_audio": 5712}
NO_REPLY = {"vad": 600, "stt": 400, "llm_first_sentence": None, "tts_first": None, "first_audio": None}


def message(token: str) -> dict | bytes:
    """短い書き方（"audio:0"・"wav"・"turn_end:null" など）を、API契約⑤のメッセージにする。"""
    name, _, arg = token.partition(":")
    if name == "ready":
        return {"type": "ready"} if arg == "nocredit" else {"type": "ready", "credit": VOICE_CREDIT}
    if name == "vad":
        return {"type": "vad", "state": arg}
    if name in ("transcript", "reply_delta"):
        return {"type": name, "text": "…"}
    if name == "audio":
        return {"type": "audio", "index": int(arg), "text": "…", "sample_rate": 24000, "bytes": WAV_BYTES}
    if name == "wav":
        return bytes(int(arg) if arg else WAV_BYTES)
    if name == "turn_end":
        return {"type": "turn_end", "latency_ms": NO_REPLY if arg == "null" else LATENCY}
    if name == "interrupted":
        return {"type": "interrupted", "index": int(arg)}
    raise ValueError(f"知らない書き方です: {token}")


WS_LOGS = [
    ("正常な1往復",
     "ready vad:speech_start vad:speech_end transcript reply_delta audio:0 wav audio:1 wav turn_end"),
    ("読み上げ中に割り込んで次のターン",
     "ready vad:speech_start vad:speech_end transcript reply_delta audio:0 wav audio:1 wav "
     "vad:speech_start interrupted:1 vad:speech_end transcript reply_delta audio:0 wav turn_end"),
    ("送り終えたあとの再生中に割り込み",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav turn_end vad:speech_start interrupted:0"),
    ("鳴り終えてから次の発話",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav turn_end "
     "vad:speech_start vad:speech_end transcript audio:0 wav turn_end"),
    ("聞き取れなかったターン",
     "ready vad:speech_start vad:speech_end transcript turn_end:null "
     "vad:speech_start vad:speech_end transcript audio:0 wav turn_end"),
    ("割り込みのあとに turn_end",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav vad:speech_start interrupted:1 turn_end"),
    ("返答中に VAD の出来事を流す",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav vad:speech_start vad:speech_end"),
    ("送っていない文の番号で止める",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav vad:speech_start interrupted:2"),
    ("WAV の長さが違う",
     "ready vad:speech_start vad:speech_end transcript audio:0 wav:99"),
    ("クレジットのない ready",
     "ready:nocredit vad:speech_start vad:speech_end"),
]


def ws_log(tokens: str) -> list[dict | bytes]:
    return [message(t) for t in tokens.split()]
