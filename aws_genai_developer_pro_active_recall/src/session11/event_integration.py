#!/usr/bin/env python3
"""セッション11: イベント駆動の統合（EventBridge → SQS → ゲートウェイ）。

    docker compose exec app python src/session11/event_integration.py

既存の業務システムに生成AIを差し込む方法は、大きく3つあります。

    API 統合     … 業務システムがゲートウェイを同期で呼ぶ（人が待っている）
    イベント駆動 … 業務システムは「起きたこと」を投げるだけ（人は待っていない）
    データ同期   … 業務データを取り込んで検索層を更新する（S3 → ナレッジベース）

ここで作るのは2番目です。**業務システムはゲートウェイを知らない**まま、
「問い合わせ票ができた」という事実だけを Amazon EventBridge に投げます。
ルールに合致したイベントは Amazon SQS に入り、こちら側が自分のペースで取り出して
ゲートウェイに通します。つなぎ先を増やすときも、業務システム側は無改修です。
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session11")

from awskit import clients  # noqa: E402

import gateway  # noqa: E402

QUEUE_NAME = "aip-c01-helpdesk-events"
DLQ_NAME = "aip-c01-helpdesk-events-dlq"
RULE_NAME = "aip-c01-ticket-created"
BUS_NAME = "default"

EVENT_SOURCE = "sample-shoji.helpdesk"
DETAIL_TYPE = "TicketCreated"

# 取り出してから処理を終えるまでの猶予。処理時間より短いと同じ票が二重に出る
VISIBILITY_TIMEOUT = "30"

# 何回失敗したら隔離キュー（DLQ）へ送るか。無限に再配信させない
MAX_RECEIVE_COUNT = "3"


def _queue_policy(queue_arn: str, rule_arn: str) -> dict:
    """キュー側のリソースベースポリシー。

    **送り手を名指しで許可する**のが要点です。`Principal` をサービスにしただけでは
    他アカウントのルールからも入れられてしまうため、`aws:SourceArn` で
    このルールからの送信だけに絞ります。
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowThisRuleOnly",
                "Effect": "Allow",
                "Principal": {"Service": "events.amazonaws.com"},
                "Action": "sqs:SendMessage",
                "Resource": queue_arn,
                "Condition": {"ArnEquals": {"aws:SourceArn": rule_arn}},
            }
        ],
    }


def ensure_pipeline(*, sqs=None, events=None) -> dict:
    """キュー・DLQ・ルール・ターゲットをそろえる（何度実行してもよい）。"""
    sqs = sqs or clients.aws("sqs")
    events = events or clients.aws("events")

    dlq_url = sqs.create_queue(QueueName=DLQ_NAME)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    rule_arn = events.put_rule(
        Name=RULE_NAME,
        EventBusName=BUS_NAME,
        State="ENABLED",
        Description="問い合わせ票の作成イベントをヘルプデスクのキューへ流す",
        # パターンに合致しないイベントは配信されない。
        # 「取ってから捨てる」のではなく「入口で絞る」のが安いやり方
        EventPattern=json.dumps(
            {"source": [EVENT_SOURCE], "detail-type": [DETAIL_TYPE]}
        ),
    )["RuleArn"]

    sqs.set_queue_attributes(
        QueueUrl=queue_url,
        Attributes={
            "Policy": json.dumps(_queue_policy(queue_arn, rule_arn)),
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": MAX_RECEIVE_COUNT}
            ),
            "VisibilityTimeout": VISIBILITY_TIMEOUT,
        },
    )
    events.put_targets(
        Rule=RULE_NAME,
        EventBusName=BUS_NAME,
        Targets=[{"Id": "helpdesk-queue", "Arn": queue_arn}],
    )
    return {
        "queueUrl": queue_url,
        "queueArn": queue_arn,
        "dlqUrl": dlq_url,
        "dlqArn": dlq_arn,
        "ruleArn": rule_arn,
    }


def drain(queue_url: str, *, sqs=None, rounds: int = 5) -> int:
    """前回の実行で残った票を捨てる（演習を何度でも同じ状態から始めるため）。"""
    sqs = sqs or clients.aws("sqs")
    removed = 0
    for _ in range(rounds):
        res = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0
        )
        messages = res.get("Messages") or []
        if not messages:
            break
        sqs.delete_message_batch(
            QueueUrl=queue_url,
            Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                for i, m in enumerate(messages)
            ],
        )
        removed += len(messages)
    return removed


def publish(tickets: list[dict], *, events=None) -> dict:
    """業務システム側の動き。**投げたら終わり**（誰が受けるかを知らない）。"""
    events = events or clients.aws("events")
    res = events.put_events(
        Entries=[
            {
                "Source": EVENT_SOURCE,
                "DetailType": DETAIL_TYPE,
                "EventBusName": BUS_NAME,
                "Detail": json.dumps(ticket, ensure_ascii=False),
            }
            for ticket in tickets
        ]
    )
    if res.get("FailedEntryCount"):
        raise RuntimeError(f"イベントの投入に失敗しました: {res['Entries']}")
    return res


def receive(queue_url: str, *, expected: int, timeout: float = 40.0, sqs=None) -> list[dict]:
    """ロングポーリングで受け取る。`WaitTimeSeconds=0` は無駄な空振りを増やす。"""
    sqs = sqs or clients.aws("sqs")
    deadline = time.monotonic() + timeout
    collected: list[dict] = []
    while len(collected) < expected and time.monotonic() < deadline:
        res = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=2
        )
        collected.extend(res.get("Messages") or [])
    return collected


def to_request(message: dict) -> dict:
    """SQS のメッセージ本文をゲートウェイの要求に変換する。

    EventBridge は「封筒（source / detail-type / time）」に「中身（detail）」を
    入れて配信します。業務データは必ず `detail` の中にあります。

    **票の ID をそのまま requestId にする**のが要点です。同じ票が2回届いても、
    ゲートウェイ側の番号札（`claim_request`）が2回目を弾きます。
    """
    envelope = json.loads(message["Body"])
    detail = envelope.get("detail", envelope)
    return {
        "requestId": detail["ticketId"],
        "conversationId": detail["ticketId"],
        "claims": detail["claims"],
        "question": detail["question"],
        "context": detail.get("context"),
        "region": detail.get("region"),
    }


def process(gw, messages: list[dict], *, queue_url: str, sqs=None) -> list[dict]:
    """取り出した票をゲートウェイに通す。**削除は処理が終わってから。**

    受け取った直後に削除すると、処理中に落ちた票が消えます。
    逆に、恒久的な失敗（403 など）を削除しないと同じ票を延々と再処理します。
    ここでは「サーバー側の一時障害（5xx）だけ残す」方針にしています。
    """
    sqs = sqs or clients.aws("sqs")
    results = []
    for message in messages:
        result = gw.handle(to_request(message))
        results.append(result)
        if result["httpStatus"] < 500:
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
    return results


TICKETS = [
    {
        "ticketId": "T-8801",
        "claims": gateway.CLAIMS["it"],
        "question": gateway.QUESTION,
        "context": gateway.CONTEXT,
    },
    {
        "ticketId": "T-8802",
        "claims": gateway.CLAIMS["finance"],
        "question": "在宅勤務は週に何日まで認められますか。",
        "context": "在宅勤務は週3日を上限として認められます。",
    },
]


def main() -> None:
    gateway.bootstrap()
    pipeline = ensure_pipeline()
    print("=== 1. 経路をそろえる ===")
    print(f"  ルール : {pipeline['ruleArn']}")
    print(f"  キュー : {pipeline['queueArn']}")
    print(f"  DLQ    : {pipeline['dlqArn']}")
    print(f"  掃除した残り票: {drain(pipeline['queueUrl'])} 件")

    print()
    print("=== 2. 業務システムがイベントを投げる ===")
    publish(TICKETS)
    print(f"  投入: {len(TICKETS)} 件（source={EVENT_SOURCE} / detail-type={DETAIL_TYPE}）")

    print()
    print("=== 3. パターンに合わないイベントは配信されない ===")
    publish_other = clients.aws("events").put_events(
        Entries=[
            {
                "Source": EVENT_SOURCE,
                "DetailType": "TicketClosed",
                "EventBusName": BUS_NAME,
                "Detail": json.dumps({"ticketId": "T-8899"}),
            }
        ]
    )
    print(f"  TicketClosed を投入（失敗 {publish_other['FailedEntryCount']} 件）")

    print()
    print("=== 4. こちら側のペースで取り出して処理する ===")
    gw = gateway.GenAIGateway()
    messages = receive(pipeline["queueUrl"], expected=len(TICKETS))
    print(f"  受信: {len(messages)} 件")
    for result in process(gw, messages, queue_url=pipeline["queueUrl"]):
        print(" ", gateway.line(result))
    print("  ※ TicketClosed は1件も届いていません（ルールで絞られました）")


if __name__ == "__main__":
    main()
