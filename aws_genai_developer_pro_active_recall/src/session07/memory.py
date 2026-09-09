#!/usr/bin/env python3
"""セッション7: エージェントの状態とメモリの置き場を分ける。

| 種類 | 何を置くか | 置き場 | いつ消えるか |
| :--- | :--- | :--- | :--- |
| 作業メモリ | いま処理中の `messages`（`toolUse` / `toolResult`） | プロセス内 | 依頼が終わったら捨てる |
| 短期メモリ | 会話の履歴（誰が何を言ったか） | DynamoDB `aip_c01_conversations`（セッション6） | 保持期間（TTL）で消す |
| 長期メモリ | 利用者の属性・確定した事実 | DynamoDB `aip_c01_agent_memory` | 明示的に消すまで残す |

作業メモリを長期メモリに混ぜると、古い資料や失敗したツール結果が翌日の回答に混ざります。
逆に長期メモリを持たないと、社員番号のような**モデルに推測させてはいけない値**の置き場が
無くなり、毎回利用者に聞き直すことになります。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/workspace")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

TABLE_NAME = "aip_c01_agent_memory"

DEFAULT_USER = "user-0042"

# 演習を何度実行しても同じ状態から始まるように置く既定の事実。
# 実運用では「利用者が確認した値だけを書く」ルールにする（モデルの推測を書かない）
DEFAULT_FACTS = {"employeeId": "EMP-0042", "department": "人事部"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_table(ddb=None):
    """長期メモリのテーブルを冪等に用意する。"""
    ddb = ddb or clients.aws("dynamodb")
    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "userId", "KeyType": "HASH"},
                {"AttributeName": "factKey", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "userId", "AttributeType": "S"},
                {"AttributeName": "factKey", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
    return ddb


def remember(ddb, user_id: str, key: str, value: str, *, source: str = "confirmed") -> None:
    """事実を1件書く。**誰が確認した値か**（source）も一緒に残す。"""
    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "userId": {"S": user_id},
            "factKey": {"S": key},
            "value": {"S": str(value)},
            "source": {"S": source},
            "updatedAt": {"S": _now()},
        },
    )


def recall(ddb, user_id: str) -> dict[str, str]:
    """その利用者について覚えている事実をすべて返す。"""
    items = ddb.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="userId = :u",
        ExpressionAttributeValues={":u": {"S": user_id}},
    )["Items"]
    return {item["factKey"]["S"]: item["value"]["S"] for item in items}


def forget(ddb, user_id: str, key: str) -> None:
    """事実を1件消す。**消せる設計にしておく**のは責任あるAIの要件でもある。"""
    ddb.delete_item(
        TableName=TABLE_NAME,
        Key={"userId": {"S": user_id}, "factKey": {"S": key}},
    )


def bootstrap(ddb=None, user_id: str = DEFAULT_USER) -> dict[str, str]:
    """既定の事実を書き込んで読み直す（演習の再現性のため）。"""
    ddb = ensure_table(ddb)
    for key, value in DEFAULT_FACTS.items():
        remember(ddb, user_id, key, value)
    return recall(ddb, user_id)
