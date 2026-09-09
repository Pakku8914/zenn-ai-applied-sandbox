#!/usr/bin/env python3
"""セッション8: 人の承認を挟むゲート（Human-in-the-loop）。

書き込みを伴う道具は、モデルが決めた瞬間に実行してはいけません。
「実行してよいか」を人が判断する場所を、**エージェントの外側**に作ります。

    executor = gated_executor(client)     # 読み取りは素通り、書き込みは止まる
    executor("reset_user_password", {"employee_id": "EMP-0042"})
    # -> isError=True「承認が必要です（承認ID xxxx）」
    decide(aid, decision="APPROVED", reviewer="admin@example.com")
    executor("reset_user_password", {"employee_id": "EMP-0042"})
    # -> 実行される（同じ承認IDで2回目は実行できない）

実務では Step Functions の `.waitForTaskToken` で待ち、承認 UI から
`SendTaskSuccess` を返します。同梱環境には承認 UI が無いため、
ここでは**同じ流れを SQS（審査待ちの通知）と DynamoDB（決裁の記録）で**表現します。
どの部品が Step Functions の何に対応するかは本文の対応表を見てください。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

QUEUE_NAME = "aip-c01-approvals"
TABLE_NAME = "aip_c01_approvals"

# 書き込みを伴う道具だけを止める。読み取りまで止めると誰も使わなくなる
WRITE_TOOLS = {"reset_user_password"}
# 審査に応じない依頼は失効させる（Step Functions なら TimeoutSeconds に相当）
REVIEW_TIMEOUT_SECONDS = 3600


def _endpoint_queue_url(queue_url: str) -> str:
    """（セッション3と同じ理由）LocalStack が返すホスト名はコンテナ内から解決できない。"""
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        return queue_url
    return f"{endpoint.rstrip('/')}{urllib.parse.urlparse(queue_url).path}"


def ensure_infra() -> tuple[object, object, str]:
    """審査キューと決裁テーブルを冪等に用意し、(sqs, ddb, queue_url) を返す。"""
    sqs = clients.aws("sqs")
    ddb = clients.aws("dynamodb")

    created = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
    queue_url = _endpoint_queue_url(created)
    try:
        sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    except ClientError:
        queue_url = created

    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "approvalId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "approvalId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
    return sqs, ddb, queue_url


def approval_id(name: str, arguments: dict) -> str:
    """同じ操作なら必ず同じ ID になる冪等キー。

    再試行やページ再読み込みで審査依頼が二重に立つのを防ぎます。
    `sort_keys=True` を忘れると、引数の順番が違うだけで別 ID になります。
    """
    payload = json.dumps(
        {"name": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def needs_review(name: str) -> bool:
    return name in WRITE_TOOLS


def get_record(aid: str, *, ddb=None) -> dict | None:
    ddb = ddb or clients.aws("dynamodb")
    item = ddb.get_item(TableName=TABLE_NAME, Key={"approvalId": {"S": aid}}).get("Item")
    if not item:
        return None
    return {key: (value.get("S") or value.get("N")) for key, value in item.items()}


def request_review(
    name: str, arguments: dict, *, requested_by: str, reason: str, infra=None
) -> str:
    """審査依頼を登録し、承認ID を返す。同じ操作の依頼は二重に作らない。"""
    sqs, ddb, queue_url = infra or ensure_infra()
    aid = approval_id(name, arguments)
    now = int(time.time())
    try:
        ddb.put_item(
            TableName=TABLE_NAME,
            Item={
                "approvalId": {"S": aid},
                "tool": {"S": name},
                "arguments": {
                    "S": json.dumps(arguments, ensure_ascii=False, sort_keys=True)
                },
                "requestedBy": {"S": requested_by},
                "reason": {"S": reason},
                "status": {"S": "PENDING"},
                "requestedAt": {"N": str(now)},
                "expiresAt": {"N": str(now + REVIEW_TIMEOUT_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(approvalId)",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return aid
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {
                "approvalId": aid,
                "tool": name,
                "arguments": arguments,
                "requestedBy": requested_by,
                "reason": reason,
            },
            ensure_ascii=False,
        ),
    )
    return aid


def decide(aid: str, *, decision: str, reviewer: str, comment: str = "", ddb=None) -> dict:
    """人の判断を記録する。PENDING からしか動かせない。"""
    if decision not in ("APPROVED", "DENIED"):
        raise ValueError("decision は APPROVED か DENIED です。")
    ddb = ddb or clients.aws("dynamodb")
    ddb.update_item(
        TableName=TABLE_NAME,
        Key={"approvalId": {"S": aid}},
        # status は DynamoDB の予約語なので #s で置き換える（直接書くと構文エラー）
        UpdateExpression="SET #s = :new, reviewer = :r, reviewComment = :c, decidedAt = :t",
        ConditionExpression="#s = :pending",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":new": {"S": decision},
            ":r": {"S": reviewer},
            ":c": {"S": comment},
            ":t": {"N": str(int(time.time()))},
            ":pending": {"S": "PENDING"},
        },
    )
    return get_record(aid, ddb=ddb)


def _blocked(message: str) -> dict:
    """ツール結果の形で「実行しなかった」ことを返す（例外を投げない）。"""
    return {"content": [{"type": "text", "text": message}], "isError": True}


def gated_executor(client, *, requested_by: str = "helpdesk-agent", infra=None, timeout: float = 10.0):
    """読み取りは素通り、書き込みは承認が下りるまで止める実行関数を返す。"""
    sqs, ddb, queue_url = infra or ensure_infra()

    def execute(name: str, arguments: dict) -> dict:
        if not needs_review(name):
            return client.call_tool(name, arguments, timeout=timeout)

        aid = approval_id(name, arguments)
        record = get_record(aid, ddb=ddb)
        if record is None:
            request_review(
                name,
                arguments,
                requested_by=requested_by,
                reason="書き込みを伴う操作",
                infra=(sqs, ddb, queue_url),
            )
            return _blocked(
                f"この操作は人の承認が必要です。審査依頼を登録しました（承認ID {aid}）。"
                "承認されるまで実行しません。"
            )

        status = record.get("status")
        if status == "PENDING":
            return _blocked(f"承認ID {aid} は審査中です。承認されるまで実行しません。")
        if status == "DENIED":
            comment = record.get("reviewComment") or "記載なし"
            return _blocked(f"承認ID {aid} は却下されました（理由: {comment}）。実行しません。")
        if status == "EXECUTED":
            return _blocked(f"承認ID {aid} は使用済みです。同じ承認で2回は実行できません。")

        # APPROVED → 実行権を1回だけ消費する。
        # 条件付き更新なので、同時に2つのプロセスが来ても片方しか通らない
        try:
            ddb.update_item(
                TableName=TABLE_NAME,
                Key={"approvalId": {"S": aid}},
                UpdateExpression="SET #s = :executed, executedAt = :t",
                ConditionExpression="#s = :approved",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":executed": {"S": "EXECUTED"},
                    ":approved": {"S": "APPROVED"},
                    ":t": {"N": str(int(time.time()))},
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return _blocked(f"承認ID {aid} の実行権は既に使われています。")
        return client.call_tool(name, arguments, timeout=timeout)

    return execute
