#!/usr/bin/env python3
"""セッション6: プロンプト利用の監査記録。

AWS CloudTrail には「誰がいつどの API を呼んだか」が残りますが、
**プロンプト本文と生成結果は残りません**。一方でアプリ側のログに本文を
全文書き込むと、機密や個人情報を別の場所へ増殖させることになります。

そこで残すのは「どの版で答えたか」を再現できる最小限にします。

    版番号 + テンプレートのハッシュ + モデル ID + トークン + 会話 ID

本文が必要な場合は、アプリのログではなく Model Invocation Logging
（Bedrock 側の設定で S3 / Amazon CloudWatch Logs へ配信）を使います。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/workspace")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

LOG_GROUP = "/sample-shoji/helpdesk/prompt-audit"

# 監査に必要な項目。ここに本文（question / answer）を足さないこと
REQUIRED_FIELDS = (
    "at",
    "promptName",
    "promptVersion",
    "promptChecksum",
    "modelId",
    "conversationId",
    "inputTokens",
    "outputTokens",
    "cacheReadInputTokens",
    "stopReason",
    "latencyMs",
)


def stream_name(conversation_id: str) -> str:
    """1会話 = 1ストリーム。追跡したい単位でストリームを分けると追いやすい。"""
    return f"converse/{conversation_id}"


def _ignore_exists(func, **kwargs) -> None:
    try:
        func(**kwargs)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise


def ensure_log_group(logs=None, *, stream: str | None = None):
    logs = logs or clients.aws("logs")
    _ignore_exists(logs.create_log_group, logGroupName=LOG_GROUP)
    if stream:
        _ignore_exists(
            logs.create_log_stream, logGroupName=LOG_GROUP, logStreamName=stream
        )
    return logs


def record(
    logs,
    *,
    stream: str,
    prompt_name: str,
    prompt_version: int,
    prompt_checksum: str,
    model_id: str,
    conversation_id: str,
    response: dict,
) -> dict:
    """1回の呼び出しを構造化ログとして1行残す。"""
    usage = response["usage"]
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "promptName": prompt_name,
        "promptVersion": prompt_version,
        "promptChecksum": prompt_checksum,
        "modelId": model_id,
        "conversationId": conversation_id,
        "inputTokens": usage["inputTokens"],
        "outputTokens": usage["outputTokens"],
        "cacheReadInputTokens": usage.get("cacheReadInputTokens", 0),
        "stopReason": response["stopReason"],
        "latencyMs": response["metrics"]["latencyMs"],
    }
    logs.put_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=stream,
        logEvents=[
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(entry, ensure_ascii=False),
            }
        ],
    )
    return entry


def read_all(logs, stream: str) -> list[dict]:
    """1ストリーム分の監査記録を古い順に読み戻す。"""
    res = logs.get_log_events(
        logGroupName=LOG_GROUP, logStreamName=stream, startFromHead=True
    )
    return [json.loads(event["message"]) for event in res["events"]]
