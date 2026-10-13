"""利用量の帳簿（セッション14の usage_book.py の写し）。

最終プロジェクトで足したのは forget() だけ：DELETE /api/me/data から呼び、その利用者の記録
（UsageLog の行と、横に持っているキャッシュのトークン数・命中の数）をまとめて消す。
"""

from __future__ import annotations

from kondate.llm import Usage
from kondate.usage import UsageLog

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

    def add_audio(self, user_id: str, kind: str, model: str, audio_seconds: float,
                  processing_seconds: float, request_id: str | None = None) -> None:
        self.log.add(user_id, kind, model, audio_seconds=round(audio_seconds, 3),
                     processing_seconds=round(processing_seconds, 3), request_id=request_id)

    def count_lookup(self, user_id: str, hit: bool) -> None:
        c = self._lookups.setdefault(user_id, dict(ZERO_LOOKUPS))
        c["hits" if hit else "misses"] += 1

    def summary(self, user_id: str) -> dict:
        mine = [r for r in self.log.records if r.user_id == user_id]

        def tokens(field: str) -> int:
            return sum(getattr(r, field) for r in mine if r.kind == "llm")

        def seconds(kind: str, field: str) -> float:
            return round(sum((getattr(r, field) for r in mine if r.kind == kind), 0.0), 3)

        return {
            "llm": {"input_tokens": tokens("input_tokens"), "output_tokens": tokens("output_tokens"),
                    **self._cache_tokens.get(user_id, ZERO_CACHE_TOKENS)},
            "stt_seconds": seconds("stt", "audio_seconds"),
            "tts_seconds": seconds("tts", "audio_seconds"),
            "stt_processing_seconds": seconds("stt", "processing_seconds"),
            "tts_processing_seconds": seconds("tts", "processing_seconds"),
            "response_cache": dict(self._lookups.get(user_id, ZERO_LOOKUPS)),
        }

    def forget(self, user_id: str) -> int:
        """最終：その利用者の記録を消し、UsageLog から消した行数を返す（2回目は 0）。"""
        before = len(self.log.records)
        self.log.records[:] = [r for r in self.log.records if r.user_id != user_id]
        self._cache_tokens.pop(user_id, None)
        self._lookups.pop(user_id, None)
        return before - len(self.log.records)
