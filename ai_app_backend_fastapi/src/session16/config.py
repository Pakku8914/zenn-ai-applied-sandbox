"""本番の設定（pydantic-settings）。必須の環境変数が無い・値がおかしいときは、起動する前に落とす。

開発用の kondate/settings.py は全項目に既定値があるので、DATABASE_URL を書き忘れても黙って起動してしまう。
ここでは本番で必ず決めるべき項目に既定値を置かず、無ければ起動しない。
エラーの表示には値（input_value）を出さない。接続文字列のパスワードや API キーがログに残るのを防ぐため。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProdSettings(BaseSettings):
    # 環境変数名はフィールド名を大文字にしたもの（database_url → DATABASE_URL）。.env は読まない
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    # ---- 必須（既定値なし）：書き忘れたら起動しない
    database_url: str
    redis_url: str
    anthropic_api_key: SecretStr
    llm_model: str

    # ---- 既定値あり：本番の標準値。変えるときだけ環境変数で上書きする
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_max_tokens: int = Field(default=1024, ge=1)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    web_workers: int = Field(default=2, ge=1, le=16)  # uvicorn のプロセス数
    graceful_timeout_seconds: int = Field(default=25, ge=1, le=300)  # uvicorn --timeout-graceful-shutdown
    drain_grace_seconds: int = Field(default=20, ge=1)  # SIGTERM 後、配信中のストリームに与える猶予
    max_streams_per_worker: int = Field(default=100, ge=1)  # 1プロセスが同時に配信するストリームの上限
    ready_timeout_seconds: float = Field(default=1.0, gt=0, le=10)  # readiness の確認1つあたりの上限
    expose_worker_pid: bool = False  # 計測用：x-kondate-worker を付ける（本番では付けない）

    @field_validator("database_url")
    @classmethod
    def _asyncpg(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("postgresql+asyncpg:// で始めてください（asyncpg で接続するため）")
        return v

    @field_validator("redis_url")
    @classmethod
    def _redis(cls, v: str) -> str:
        if urlsplit(v).scheme not in ("redis", "rediss"):
            raise ValueError("redis:// か rediss:// で始めてください")
        return v

    @field_validator("anthropic_api_key")
    @classmethod
    def _not_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().strip():
            raise ValueError("空にしないでください")
        return v

    @field_validator("anthropic_base_url")
    @classmethod
    def _no_v1(cls, v: str) -> str:
        if v.rstrip("/").endswith("/v1"):
            raise ValueError("末尾に /v1 を付けないでください（SDK が /v1/messages を足します）")
        return v.rstrip("/")

    @model_validator(mode="after")
    def _shutdown_order(self) -> ProdSettings:
        # drain の締め切りが uvicorn の猶予より後だと、error を送る前に uvicorn がタスクを打ち切ってしまう
        if self.drain_grace_seconds >= self.graceful_timeout_seconds:
            raise ValueError(f"DRAIN_GRACE_SECONDS（{self.drain_grace_seconds} 秒）は "
                             f"GRACEFUL_TIMEOUT_SECONDS（{self.graceful_timeout_seconds} 秒）より短くしてください")
        return self

    @property
    def upstream_is_mock(self) -> bool:
        """接続先が mockllm か。遅延・障害注入ヘッダの転送と、readiness で上流を見るかの判断に使う。"""
        return urlsplit(self.anthropic_base_url).hostname == "mockllm"

    def summary(self) -> str:
        """起動時に表示してよい値だけ（秘密を含まないもの）。"""
        return (f"WEB_WORKERS={self.web_workers} GRACEFUL_TIMEOUT_SECONDS={self.graceful_timeout_seconds} "
                f"DRAIN_GRACE_SECONDS={self.drain_grace_seconds} MAX_STREAMS_PER_WORKER={self.max_streams_per_worker}")


# pydantic のエラーの種類 → 日本語の理由。ctx（制約の値）だけを使い、入力値は使わない
REASONS: dict[str, Callable[[dict], str]] = {
    "missing": lambda c: "必須です（環境変数が設定されていません）",
    "greater_than_equal": lambda c: f"{c['ge']} 以上にしてください",
    "less_than_equal": lambda c: f"{c['le']} 以下にしてください",
    "greater_than": lambda c: f"{c['gt']} より大きくしてください",
    "int_parsing": lambda c: "整数にしてください",
    "float_parsing": lambda c: "数値にしてください",
    "bool_parsing": lambda c: "true か false にしてください",
    "value_error": lambda c: str(c["error"]),
}


def describe_errors(exc: ValidationError) -> list[str]:
    """ValidationError を「- 環境変数名: 理由」の行にする。値（input_value）は含めない。"""
    lines: list[str] = []
    for err in exc.errors(include_url=False, include_input=False):
        name = ".".join(str(p) for p in err["loc"]).upper() or "設定の組み合わせ"
        reason = REASONS.get(err["type"])
        text = reason(err.get("ctx", {})) if reason else f"値が正しくありません（{err['type']}）"
        lines.append(f"- {name}: {text}")
    return lines


def load_settings_or_exit() -> ProdSettings:
    """設定を読み、足りなければ理由を標準エラーに並べて終了コード 1 で止まる。"""
    try:
        return ProdSettings()  # type: ignore[call-arg]  # 必須項目は環境変数から読む
    except ValidationError as exc:
        lines = describe_errors(exc)
        print(f"設定エラー：起動を中止します（{len(lines)} 件）", *lines, sep="\n", file=sys.stderr)
        raise SystemExit(1) from None
