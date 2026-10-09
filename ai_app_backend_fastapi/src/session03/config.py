"""セッション3の設定。値は環境変数から読み、モデル ID と API キーをコードに書かない。"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    # 環境変数名はフィールド名を大文字にしたもの（anthropic_api_key → ANTHROPIC_API_KEY）
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: SecretStr  # 既定値なし：無ければ起動時に ValidationError で止める
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_model: str  # 既定値なし：compose.yaml か .env の LLM_MODEL で渡す
    llm_max_tokens: int = Field(default=1024, gt=0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)  # read・write・pool の上限
    llm_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    # リトライはセッション11で設計する。それまでは失敗をそのまま観察するため 0 にしておく
    llm_max_retries: int = Field(default=0, ge=0)

    @property
    def forwards_mock_headers(self) -> bool:
        """障害注入ヘッダ（x-mock-*）を上流へ渡してよいか。接続先が mockllm のときだけ True。"""
        return urlsplit(self.anthropic_base_url).hostname == "mockllm"


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
