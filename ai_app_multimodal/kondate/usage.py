"""利用量の記録（①バックエンド編の課金計測の最小版）。①は PostgreSQL に保存するが、本書はメモリ＋任意の JSON Lines。

LLM はトークン、音声認識・音声合成は「音声の秒数」と「処理にかかった CPU 秒数」を記録する。
時刻は注入した時計から取る（datetime.now() を直接呼ばない）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kondate.clock import Clock, SystemClock


@dataclass(frozen=True)
class UsageRecord:
    at: str
    user_id: str
    kind: str                      # "llm" / "stt" / "tts"
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    processing_seconds: float = 0.0
    request_id: str | None = None


@dataclass
class UsageLog:
    clock: Clock = field(default_factory=SystemClock)
    path: Path | None = None       # 指定すると1行1レコードで追記する
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, user_id: str, kind: str, model: str, **values) -> UsageRecord:
        rec = UsageRecord(at=self.clock.now().isoformat(), user_id=user_id, kind=kind, model=model, **values)
        self.records.append(rec)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        return rec

    def totals(self, user_id: str | None = None) -> dict:
        out = {"input_tokens": 0, "output_tokens": 0, "audio_seconds": 0.0, "processing_seconds": 0.0}
        for r in self.records:
            if user_id is None or r.user_id == user_id:
                out["input_tokens"] += r.input_tokens
                out["output_tokens"] += r.output_tokens
                out["audio_seconds"] = round(out["audio_seconds"] + r.audio_seconds, 3)
                out["processing_seconds"] = round(out["processing_seconds"] + r.processing_seconds, 3)
        return out
