#!/usr/bin/env python3
"""セッション13: 保持期間を1か所にまとめる。

同じデータの写しが3か所にあれば、**実効保持期間は最長の場所**で決まります。
DynamoDB の TTL を30日にしても、S3 の写しが365日残り、ログが400日残るなら、
その会話は400日残ります。だから日数はここだけに書き、
DynamoDB・S3・CloudWatch Logs の3か所へ**この表から**設定します。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session06")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import conversation_store as store  # noqa: E402

BUCKET = "sample-shoji-transcripts"
LOG_GROUP = "/sample-shoji/helpdesk/conversation-log"

# 会話履歴の日数はセッション6の実装が持っている。**二重に定義しない**
CONVERSATION_DAYS = store.RETENTION_DAYS

RETENTION: dict[str, int] = {
    # DynamoDB: 1行ごとの `expiresAt` に入れる日数
    "conversation_ttl_days": CONVERSATION_DAYS,
    # S3: raw/ に置いた書き起こし（匿名化前の一時ファイル）
    "raw_prefix_days": 7,
    # S3: anonymized/ をアーカイブへ移す日数と、削除する日数
    "anonymized_archive_days": 30,
    "anonymized_expire_days": 365,
    # CloudWatch Logs: 会話に紐づく動作ログ。会話履歴と同じ日数にそろえる
    "log_retention_days": CONVERSATION_DAYS,
}

LIFECYCLE: dict = {
    "Rules": [
        {
            "ID": "expire-raw-transcripts",
            "Status": "Enabled",
            "Filter": {"Prefix": "raw/"},
            "Expiration": {"Days": RETENTION["raw_prefix_days"]},
        },
        {
            "ID": "archive-then-expire-anonymized",
            "Status": "Enabled",
            "Filter": {"Prefix": "anonymized/"},
            "Transitions": [
                {
                    "Days": RETENTION["anonymized_archive_days"],
                    "StorageClass": "GLACIER",
                }
            ],
            "Expiration": {"Days": RETENTION["anonymized_expire_days"]},
        },
        {
            # 中断したマルチパートアップロードは、消えないまま課金され続ける
            "ID": "abort-stalled-uploads",
            "Status": "Enabled",
            "Filter": {"Prefix": "upload/"},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        },
    ]
}


def ensure_bucket(s3=None):
    """書き起こしの置き場を冪等に用意する。"""
    s3 = s3 or clients.aws("s3")
    try:
        s3.create_bucket(Bucket=BUCKET)
    except ClientError as error:
        if error.response["Error"]["Code"] not in (
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        ):
            raise
    return s3


def apply_s3_lifecycle(s3) -> list[dict]:
    """ライフサイクルを設定して、**読み戻した結果**を返す。"""
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET, LifecycleConfiguration=LIFECYCLE
    )
    return s3.get_bucket_lifecycle_configuration(Bucket=BUCKET)["Rules"]


def apply_dynamodb_ttl(ddb) -> dict:
    """TTL を有効にして、読み戻した状態を返す。"""
    try:
        ddb.update_time_to_live(
            TableName=store.TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
    except ClientError as error:
        # すでに有効なら ValidationException。冪等に扱う
        if error.response["Error"]["Code"] != "ValidationException":
            raise
    return ddb.describe_time_to_live(TableName=store.TABLE_NAME)[
        "TimeToLiveDescription"
    ]


def apply_log_retention(logs=None) -> dict:
    """ロググループの保持日数を設定して、読み戻した定義を返す。"""
    logs = logs or clients.aws("logs")
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    logs.put_retention_policy(
        logGroupName=LOG_GROUP, retentionInDays=RETENTION["log_retention_days"]
    )
    groups = logs.describe_log_groups(logGroupNamePrefix=LOG_GROUP)["logGroups"]
    found = [g for g in groups if g["logGroupName"] == LOG_GROUP]
    return found[0] if found else {}


def prefix_of(rule: dict) -> str:
    """`Filter` でも古い `Prefix` でも読めるようにする。"""
    if "Filter" in rule:
        target = rule["Filter"]
        return target.get("Prefix") or (target.get("And") or {}).get("Prefix", "")
    return rule.get("Prefix", "")


def expiration_days(rule: dict) -> int | None:
    return (rule.get("Expiration") or {}).get("Days")


def apply_all(*, s3=None, ddb=None, logs=None) -> dict:
    """3か所へ同じ表から設定し、読み戻した結果をまとめて返す。"""
    s3 = ensure_bucket(s3)
    ddb = ddb or store.ensure_table()
    return {
        "lifecycle": apply_s3_lifecycle(s3),
        "ttl": apply_dynamodb_ttl(ddb),
        "logGroup": apply_log_retention(logs),
    }


def inconsistencies() -> list[str]:
    """日数の矛盾を返す（空なら合格）。表を直したときにここが赤くなる。"""
    issues: list[str] = []
    if RETENTION["raw_prefix_days"] > RETENTION["conversation_ttl_days"]:
        issues.append("匿名化前の書き起こしが、会話履歴より長く残る")
    if RETENTION["log_retention_days"] != RETENTION["conversation_ttl_days"]:
        issues.append("ログの保持日数が会話履歴の TTL と一致しない")
    if RETENTION["anonymized_archive_days"] > RETENTION["anonymized_expire_days"]:
        issues.append("アーカイブへ移す前に削除される設定になっている")
    return issues


def main() -> None:
    print("=== 保持期間の表（ここだけを直す） ===")
    for key, days in RETENTION.items():
        print(f"{key} = {days}日")

    applied = apply_all()

    print()
    print("=== 設定して読み戻した結果 ===")
    ttl = applied["ttl"]
    print(f"DynamoDB TTL: {ttl.get('TimeToLiveStatus')} / {ttl.get('AttributeName')}")
    for rule in applied["lifecycle"]:
        days = expiration_days(rule)
        transitions = rule.get("Transitions") or []
        extra = (
            f" transition={transitions[0]['Days']}日→{transitions[0]['StorageClass']}"
            if transitions
            else ""
        )
        print(f"S3: {rule['ID']} prefix={prefix_of(rule)} expire={days or '-'}{extra}")
    print(
        f"CloudWatch Logs: {applied['logGroup'].get('logGroupName')} = "
        f"{applied['logGroup'].get('retentionInDays')}日"
    )

    print()
    print(f"日数の矛盾: {inconsistencies() or 'なし'}")


if __name__ == "__main__":
    main()
