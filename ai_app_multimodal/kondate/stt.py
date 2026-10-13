"""音声認識（faster-whisper・CPU・int8）。モデルはプロセスに1つだけ読み込む。

モデルのファイルは初回だけ Hugging Face から取得し、名前付きボリューム /models（HF_HOME）にキャッシュする。
revision を固定しているので、同じモデル名でも中身が勝手に変わらない。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from faster_whisper import WhisperModel, download_model

from kondate.settings import get_settings

# Systran/faster-whisper-* のコミット（2026-10-02 に取得したもの）
REVISIONS = {
    "tiny": "d90ca5fe260221311c53c58e660288d3deb8d356",
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    "small": "536b0662742c02347bc0e980a01041f333bce120",
}


@dataclass(frozen=True)
class SttResult:
    text: str
    audio_seconds: float
    processing_seconds: float

    @property
    def rtf(self) -> float:
        """実時間比（処理時間 ÷ 音声の長さ）。1.0 未満なら音声より速く処理できている。"""
        return self.processing_seconds / self.audio_seconds if self.audio_seconds else 0.0


def model_path(name: str | None = None, *, local_only: bool = False) -> str:
    name = name or get_settings().whisper_model
    return download_model(name, revision=REVISIONS.get(name), local_files_only=local_only)


def is_cached(name: str | None = None) -> bool:
    try:
        model_path(name, local_only=True)
        return True
    except Exception:  # キャッシュに無いと huggingface_hub の例外になる（種類はバージョンで変わる）
        return False


@lru_cache
def get_model(name: str | None = None) -> WhisperModel:
    s = get_settings()
    return WhisperModel(model_path(name), device="cpu", compute_type=s.whisper_compute_type, cpu_threads=s.whisper_cpu_threads)


def transcribe(audio: np.ndarray, sample_rate: int, *, model: str | None = None, language: str = "ja") -> SttResult:
    """16kHz モノラルの float32 配列を文字にする。CPU を使い切る同期処理なので、async の中ではスレッドに逃がして呼ぶ。"""
    s = get_settings()
    if sample_rate != s.stt_sample_rate:
        raise ValueError(f"サンプリングレートは {s.stt_sample_rate}Hz にしてください（受け取ったのは {sample_rate}Hz）")
    m = get_model(model)
    started = time.perf_counter()
    segments, _info = m.transcribe(audio, language=language, beam_size=s.whisper_beam_size, condition_on_previous_text=False)
    text = "".join(seg.text for seg in segments).strip()  # segments は遅延評価。ここで実際に認識が走る
    return SttResult(text, len(audio) / sample_rate, time.perf_counter() - started)
