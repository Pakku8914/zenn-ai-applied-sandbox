"""利用量の帳簿：kondate.usage.UsageLog に記録し、GET /api/usage の形にまとめる。

UsageLog の1件（UsageRecord）が持つのは、トークン2項目と秒数2項目だけ。プロンプトキャッシュの2項目と、
応答キャッシュの命中・外れの数は、利用者ごとの合計だけをこの帳簿の横に持つ。
UsageLog.totals() は音声認識と音声合成の秒数を足し合わせてしまうので、種類（kind）ごとに数え直す。
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

    def forget(self, user_id: str) -> None:
        """利用者ごとの横持ち（キャッシュの2項目・命中と外れ）を消す。記録（log.records）は前章の forget_usage が消す。"""
        self._cache_tokens.pop(user_id, None)
        self._lookups.pop(user_id, None)

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
