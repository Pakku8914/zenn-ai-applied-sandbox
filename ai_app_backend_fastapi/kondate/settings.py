"""設定は環境変数から読む（pydantic-settings）。モデル ID を書いてよいのはここと compose.yaml だけ。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    llm_model: str = "claude-sonnet-5-5"
    llm_model_light: str = "claude-haiku-4-5"
    llm_max_tokens: int = 1024
    database_url: str = "postgresql+asyncpg://kondate:kondate@postgres:5432/kondate"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    mockllm_url: str = "http://mockllm:8080"
    api_base_url: str = "http://api:8000"
    data_dir: str = "/app/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
