"""教材の全章で使う AWS クライアントの生成口。

**この関数群のシグネチャは章をまたいで変更しません**（`requirements.md`「API契約」参照）。
実 AWS へ向けるかモックへ向けるかは環境変数だけで切り替わるため、
本文のコード例は「モック用に書き換えたコード」ではなく、
そのまま実 AWS でも動くコードになっています。

    BEDROCK_ENDPOINT   … Bedrock 互換モックの URL（未設定なら実 AWS）
    AWS_ENDPOINT_URL   … LocalStack の URL（未設定なら実 AWS）
"""

from __future__ import annotations

import os

import boto3
from botocore.config import Config

DEFAULT_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _bedrock_config(max_attempts: int = 3, mode: str = "standard") -> Config:
    """リトライ方針を明示した Config を返す。

    boto3 の既定は `legacy`（最大3回・リトライ対象が狭い）です。
    Bedrock のスロットリングを扱うなら `standard` 以上を明示するのが実務の作法なので、
    教材では最初から明示します（詳細はコスト・信頼性のセッションで扱います）。
    """
    return Config(
        region_name=DEFAULT_REGION,
        retries={"max_attempts": max_attempts, "mode": mode},
        # ストリーミングを扱うため読み取りタイムアウトは長めに取る
        read_timeout=60,
        connect_timeout=5,
    )


def bedrock(**kwargs):
    """コントロールプレーン（モデル一覧・カスタムモデル・評価ジョブなど）。"""
    return boto3.client(
        "bedrock",
        endpoint_url=os.environ.get("BEDROCK_ENDPOINT"),
        config=_bedrock_config(),
        **kwargs,
    )


def bedrock_runtime(max_attempts: int = 3, mode: str = "standard", **kwargs):
    """データプレーン（InvokeModel / Converse / ApplyGuardrail）。"""
    return boto3.client(
        "bedrock-runtime",
        endpoint_url=os.environ.get("BEDROCK_ENDPOINT"),
        config=_bedrock_config(max_attempts=max_attempts, mode=mode),
        **kwargs,
    )


def agent_runtime(**kwargs):
    """Knowledge Bases / エージェントの実行（Retrieve / RetrieveAndGenerate / Rerank）。"""
    return boto3.client(
        "bedrock-agent-runtime",
        endpoint_url=os.environ.get("BEDROCK_ENDPOINT"),
        config=_bedrock_config(),
        **kwargs,
    )


def aws(service: str, **kwargs):
    """Bedrock 以外の AWS サービス（S3・DynamoDB・SQS など）を LocalStack 経由で使う。"""
    return boto3.client(
        service,
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=DEFAULT_REGION,
        **kwargs,
    )


def pg_dsn() -> str:
    """pgvector を載せた PostgreSQL の接続文字列。"""
    return os.environ.get(
        "PG_DSN", "postgresql://genai:sandbox@postgres:5432/genai"
    )


def mock_base_url() -> str:
    """モック専用の制御 API（/_mock/*）を叩くためのベース URL。"""
    return os.environ.get("BEDROCK_ENDPOINT", "http://bedrock-mock:8080")
