"""設定は環境変数から読む（pydantic-settings）。モデル ID を書いてよいのはここと compose.yaml だけ。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # LLM（既定は mockllm。接続先とキーは anthropic SDK が ANTHROPIC_BASE_URL・ANTHROPIC_API_KEY から読む）
    llm_model: str = "claude-sonnet-5-5"
    llm_model_light: str = "claude-haiku-4-5"
    llm_max_tokens: int = 1024
    mockllm_url: str = "http://mockllm:8080"

    # 音声合成（VOICEVOX ENGINE）。話者は1つに固定する：3 = ずんだもん（ノーマル）
    voicevox_url: str = "http://voicevox:50021"
    voicevox_speaker: int = 3
    voicevox_credit: str = "VOICEVOX:ずんだもん"

    # 音声認識（faster-whisper）。モデルは名前付きボリューム /models（HF_HOME）にキャッシュされる
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_cpu_threads: int = 2
    whisper_beam_size: int = 1
    stt_sample_rate: int = 16000

    # アップロード
    upload_max_bytes: int = 10 * 1024 * 1024
    image_max_long_edge: int = 1568

    api_base_url: str = "http://api:8000"
    data_dir: str = "/app/data"
    media_dir: str = "/app/media"


@lru_cache
def get_settings() -> Settings:
    return Settings()
