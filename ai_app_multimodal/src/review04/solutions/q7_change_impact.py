"""問題7：設定を1つ変えたとき、どこに影響が出るかを機械で洗い出す（S3・S8・S12・S13・S14）。

    docker compose exec api python -m src.review04.solutions.q7_change_impact

モデル ID は表示しない（LLM_MODEL・LLM_MODEL_LIGHT の名前で表す）。CER と RTF はセッション8の表の値。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

from kondate.media import media_path
from kondate.settings import get_settings
from src.review04.kit import (
    FRAME_TOKENS, FRIDGE_PROMPT, FRIDGE_SCHEMA, RETENTION, RULES,
    cache_key, estimate_image_tokens, find_regressions, fit_long_edge, sha256_hex, text_tokens,
)

settings = get_settings()
PHOTO = (1280, 960)                 # media/fridge.jpg
WAIT_BUDGET = Decimal("5")          # 待ってよい時間 B（秒・セッション14）
UTTERANCE = Decimal("4")            # 1発話の長さ（秒・セッション14の仮定）
# セッション8の比較（辞書なし）の CER。RTF は small がセッション14の見積もりの値、base はセッション8の表の値
CER = {"small": 0.115, "base": 0.321}
RTF = {"small": Decimal("0.6"), "base": Decimal("0.208")}
LLM_FIELDS = ("model_env", "max_long_edge", "jpeg_quality", "prompt")


@dataclass(frozen=True)
class Config:
    model_env: str = "LLM_MODEL"
    max_long_edge: int = 1568
    jpeg_quality: int = 90
    prompt: str = FRIDGE_PROMPT
    cache_ttl_hours: int = 24
    whisper: str = "small"


CHANGES = [
    ("モデルを LLM_MODEL_LIGHT に替える", {"model_env": "LLM_MODEL_LIGHT"}),
    ("縮小の上限を 1092 にする", {"max_long_edge": 1092}),
    ("指示文に「調味料は除いてください。」を足す", {"prompt": FRIDGE_PROMPT + "調味料は除いてください。"}),
    ("応答キャッシュの保持時間を 48 時間にする", {"cache_ttl_hours": 48}),
    ("Whisper のモデルを base にする", {"whisper": "base"}),
]


def model_of(c: Config) -> str:
    return settings.llm_model if c.model_env == "LLM_MODEL" else settings.llm_model_light


def key_of(c: Config, content: str) -> str:
    """冷蔵庫の写真の応答キャッシュのキー（セッション14）。"""
    return cache_key(scope="u001", kind="fridge_scan", content_sha256=content,
                     preprocess={"max_long_edge": c.max_long_edge, "jpeg_quality": c.jpeg_quality},
                     prompt=c.prompt, system=None, model=model_of(c), schema=FRIDGE_SCHEMA)


def input_tokens(c: Config) -> int:
    """fridge.jpg 1枚の入力（セッション3の式）。"""
    return FRAME_TOKENS + estimate_image_tokens(*fit_long_edge(*PHOTO, c.max_long_edge)) + text_tokens(c.prompt)


def evaluation(base: Config, c: Config) -> str:
    """やり直す評価（セッション12）。CER は基準と比べ、回帰の数まで出す。"""
    if any(getattr(base, f) != getattr(c, f) for f in LLM_FIELDS):
        return "抽出をやり直す"
    if base.whisper != c.whisper:
        rule = {"cer.weighted_strict": RULES["cer.weighted_strict"]}
        found = find_regressions({"deterministic": {"cer.weighted_strict": CER[c.whisper]}},
                                 {"deterministic": {"cer.weighted_strict": CER[base.whisper]}}, rule)
        return f"CER {CER[base.whisper]} → {CER[c.whisper]}（回帰 {len(found)} 件）"
    return "不要"


def retention(c: Config) -> str:
    """応答キャッシュは、元の写真の保持期限（セッション13の upload）より長く残さない。"""
    return "OK" if timedelta(hours=c.cache_ttl_hours) <= RETENTION["upload"] else "NG"


def stt_queue(c: Config) -> int:
    """待ち行列の上限 ＝ ⌊B ÷ S⌋ × 同時実行数（セッション14）。S ＝ 1発話の長さ × RTF。"""
    return math.floor(WAIT_BUDGET / (UTTERANCE * RTF[c.whisper])) * 1


def run() -> list[str]:
    content = sha256_hex(media_path("fridge.jpg").read_bytes())
    base = Config()
    lines = [f"基準 → 入力 {input_tokens(base)}・STT 待ち行列 {stt_queue(base)}"]
    for n, (label, change) in enumerate(CHANGES, 1):
        c = replace(base, **change)
        cache = "そのまま" if key_of(c, content) == key_of(base, content) else "外れる"
        price = "見直す" if c.model_env != base.model_env else "そのまま"
        lines.append(f"{n}. {label} → キャッシュ {cache}・入力 {input_tokens(c)}・評価 {evaluation(base, c)}"
                     f"・保持期限 {retention(c)}・単価表 {price}・STT 待ち行列 {stt_queue(c)}")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
