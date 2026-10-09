"""最終プロジェクトの設定（pydantic-settings）。接続先・モデル ID は kondate/settings.py（LLM_MODEL など）から読む。

ここに置くのは、最終プロジェクトで足した設定だけ。環境変数名はフィールド名を大文字にしたもの。
本番で起動前に検証したいときは Session 16 の ProdSettings の考え方（必須項目に既定値を置かない）を足す。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SYSTEM_PROMPT = ("あなたは献立相談AI「こんだてAI」です。レシピの情報は必ずツールで調べ、推測で答えないでください。"
                 "1週間ぶんの献立を頼まれたら plan_week でジョブを始め、結果は画面の進捗表示で届くと伝えてください。")


class FinalSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    cors_origins: str = "http://localhost:3710"  # カンマ区切り。②はサーバ側から呼ぶのが既定（ブラウザから直接は呼ばない）
    trust_request_id: bool = True  # ②が付けた x-request-id（req_ + ULID）を使う
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    history_max_input_tokens: int = Field(default=8000, gt=0)  # 履歴＋新しい発言＋ツール定義の見積もりの上限
    deadline_seconds: float = Field(default=20.0, gt=0)  # 先読みまでのリトライとフォールバックの合計時間
    max_attempts: int = Field(default=2, ge=1)  # 経路ごとの試行回数（最初の1回を含む）
    breaker_failures: int = Field(default=5, ge=1)
    breaker_open_seconds: float = Field(default=30.0, gt=0)
    max_streams_per_worker: int = Field(default=100, ge=1)
    drain_grace_seconds: int = Field(default=20, ge=1)
    ready_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upstream_is_mock(self) -> bool:
        """上流が mockllm か。x-mock-* の転送と、readiness で上流を見るかの判断に使う（本物の API には転送しない）。"""
        return urlsplit(self.anthropic_base_url).hostname == "mockllm"
