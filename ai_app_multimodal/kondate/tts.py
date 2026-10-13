"""音声合成（VOICEVOX ENGINE の HTTP API）。話者は settings.voicevox_speaker の1つに固定する。

VOICEVOX で作った音声を使うときは、クレジット表記（settings.voicevox_credit＝「VOICEVOX:ずんだもん」）が必要。
"""

from __future__ import annotations

import io
import time
import wave
from dataclasses import dataclass

import httpx2

from kondate.settings import get_settings

# 読み間違いを直すユーザー辞書。VOICEVOX は「鶏むね肉」を「ニワトリムネニク」と読む（2026-10-02・0.25.2 で確認）
USER_DICT = [
    {"surface": "鶏むね肉", "pronunciation": "トリムネニク", "accent_type": 3},
]


@dataclass(frozen=True)
class TtsResult:
    wav: bytes
    kana: str
    audio_seconds: float
    processing_seconds: float

    @property
    def rtf(self) -> float:
        return self.processing_seconds / self.audio_seconds if self.audio_seconds else 0.0


class Voicevox:
    def __init__(self, base_url: str | None = None, speaker: int | None = None, timeout: float = 60.0) -> None:
        s = get_settings()
        self.speaker = speaker if speaker is not None else s.voicevox_speaker
        self._client = httpx2.AsyncClient(base_url=base_url or s.voicevox_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def version(self) -> str:
        r = await self._client.get("/version")
        r.raise_for_status()
        return r.json()

    async def ensure_user_dict(self, words: list[dict] = USER_DICT) -> int:
        """USER_DICT の語が未登録なら登録する（何度呼んでもよい）。登録した数を返す。"""
        r = await self._client.get("/user_dict")
        r.raise_for_status()
        registered = {(w["surface"], w["pronunciation"]) for w in r.json().values()}
        added = 0
        for w in words:
            if (w["surface"], w["pronunciation"]) in registered:
                continue
            r = await self._client.post("/user_dict_word", params=w)
            r.raise_for_status()
            added += 1
        return added

    async def synthesize(self, text: str, *, sample_rate: int = 16000) -> TtsResult:
        """文を WAV（PCM 16bit・モノラル）にする。音声認識にそのまま渡せるよう、既定は 16kHz で出力させる。"""
        started = time.perf_counter()
        q = await self._client.post("/audio_query", params={"text": text, "speaker": self.speaker})
        q.raise_for_status()
        query = q.json()
        query["outputSamplingRate"] = sample_rate
        query["outputStereo"] = False
        r = await self._client.post("/synthesis", params={"speaker": self.speaker}, json=query)
        r.raise_for_status()
        elapsed = time.perf_counter() - started
        wav = r.content
        with wave.open(io.BytesIO(wav)) as wf:
            seconds = wf.getnframes() / wf.getframerate()
        return TtsResult(wav, query["kana"], seconds, elapsed)
