#!/usr/bin/env python3
"""セッション14: 継続監視（ガバナンスの証跡として何を数え、いつ人を呼ぶか）。

    docker compose exec app python src/session14/continuous_monitoring.py

説明責任ログは1件ずつの証跡です。**傾向は数えないと見えません。**
本章で数えるのは、性能の指標ではなく「ガバナンス上の証跡」の3本です。

    拒否率       ガードレールが入口で止めた割合  → 誤用の兆候・ポリシーの効き過ぎ
    引用ゼロ率   根拠が引けなかった割合          → 資料の欠落・索引の壊れ・分類の誤り
    exhausted率  上位モデルでも救えなかった割合  → 資料の陳腐化・想定外の問い合わせ

しきい値を超えたら通知します。人向けは Amazon SNS、機械向け（自動修復の起点）は
Amazon EventBridge です。**実際の是正処理**（再索引・ポリシー見直し・人への切替）は
AWS Lambda や AWS Systems Manager Automation に置きますが、どちらも
LocalStack Community にはないため、ここでは Amazon SQS で「起動要求が届いた」
ところまでを確かめます。

ダッシュボードの作り方・アラームの運用・レイテンシやエラー率の監視は
「セッション17」の範囲です。ここは**ガバナンスとして何を集計するか**までにとどめます。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session14")

from awskit import clients  # noqa: E402

import provenance  # noqa: E402

NAMESPACE = "SampleShoji/Governance"
COUNT_METRIC = "GovernanceEvaluated"

# 集計キー → CloudWatch のメトリクス名
METRIC_OF = {
    "blockedRate": "GuardrailBlockRate",
    "zeroCitationRate": "ZeroCitationRate",
    "exhaustedRate": "ExhaustedRate",
}

# しきい値。**根拠を書けない数字は置かない**（ここは初期値で、見直し前提）
THRESHOLDS = {
    "blockedRate": 0.20,
    "zeroCitationRate": 0.10,
    "exhaustedRate": 0.10,
}

# 超過したときに何を起動するか。イベントに載せて自動修復側へ渡す
REMEDIATION = {
    "blockedRate": "review-denied-topics",
    "zeroCitationRate": "reindex-corpus",
    "exhaustedRate": "escalate-to-human",
}

TOPIC_NAME = "aip-c01-governance-alerts"
INBOX_QUEUE = "aip-c01-governance-inbox"
ACTION_QUEUE = "aip-c01-governance-actions"
RULE_NAME = "aip-c01-governance-breach"
BUS_NAME = "default"

EVENT_SOURCE = "sample-shoji.governance"
DETAIL_TYPE = "GovernanceThresholdBreached"


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def aggregate(entries: list[dict]) -> dict:
    """説明責任ログを数える。**分母をどこに置くかが設計判断です。**

    - 拒否率の分母は「全件」。入口で止めた件も含めた全体に対する割合を見たい
    - 引用ゼロ率と exhausted 率の分母は「入口を通った件」。止めた件には
      そもそも引用が無いので、全件を分母にすると拒否が増えるほど
      引用ゼロ率が下がって見える（＝悪化を見逃す）
    """
    counts = {outcome: 0 for outcome in provenance.OUTCOMES}
    for entry in entries:
        counts[entry["outcome"]] += 1
    total = len(entries)
    attempted = total - counts["blocked"]
    return {
        "total": total,
        "attempted": attempted,
        **counts,
        "blockedRate": _rate(counts["blocked"], total),
        "zeroCitationRate": _rate(counts["no_citation"], attempted),
        "exhaustedRate": _rate(counts["exhausted"], attempted),
        "groundedRate": _rate(counts["answered"], attempted),
        "measuredAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def breaches(summary: dict, thresholds: dict | None = None) -> list[dict]:
    """しきい値を超えた項目だけを返す（空なら通知しない）。"""
    thresholds = thresholds or THRESHOLDS
    found = []
    for key in sorted(thresholds):
        value = summary[key]
        if value > thresholds[key]:
            found.append(
                {
                    "metric": key,
                    "metricName": METRIC_OF[key],
                    "value": value,
                    "threshold": thresholds[key],
                    "action": REMEDIATION[key],
                }
            )
    return found


# ---------------------------------------------------------------------------
# メトリクス（CloudWatch のカスタムメトリクス）
# ---------------------------------------------------------------------------


def dimensions(run_id: str) -> list[dict]:
    """実行ごとにディメンションを分ける（演習を何度実行しても値が混ざらない）。"""
    return [
        {"Name": "Assistant", "Value": "helpdesk"},
        {"Name": "RunId", "Value": run_id},
    ]


def publish_metrics(cw, summary: dict, *, run_id: str) -> list[str]:
    """3本の割合と、母数を1本。**母数を出さない割合は読めません。**

    「拒否率 50%」が2件中1件なのか2,000件中1,000件なのかで対応は変わります。
    """
    now = datetime.now(timezone.utc)
    data = [
        {
            "MetricName": COUNT_METRIC,
            "Dimensions": dimensions(run_id),
            "Timestamp": now,
            "Value": float(summary["total"]),
            "Unit": "Count",
        }
    ]
    for key, name in METRIC_OF.items():
        data.append(
            {
                "MetricName": name,
                "Dimensions": dimensions(run_id),
                "Timestamp": now,
                "Value": round(summary[key] * 100, 4),  # Percent は 0〜100 で入れる
                "Unit": "Percent",
            }
        )
    cw.put_metric_data(Namespace=NAMESPACE, MetricData=data)
    return [item["MetricName"] for item in data]


def listed_metrics(cw, *, run_id: str) -> list[str]:
    """登録されたメトリクスを読み戻す（この実行ぶんだけ抜き出す）。"""
    names: set[str] = set()
    token: str | None = None
    while True:
        kwargs = {"Namespace": NAMESPACE}
        if token:
            kwargs["NextToken"] = token
        res = cw.list_metrics(**kwargs)
        for metric in res.get("Metrics", []):
            values = {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}
            if values.get("RunId") == run_id:
                names.add(metric["MetricName"])
        token = res.get("NextToken")
        if not token:
            return sorted(names)


def read_count_metric(cw, *, run_id: str, attempts: int = 20, wait: float = 0.5):
    """母数のメトリクスを合計で読み戻す。書けたことを値で確かめるため。"""
    for _ in range(attempts):
        res = cw.get_metric_statistics(
            Namespace=NAMESPACE,
            MetricName=COUNT_METRIC,
            Dimensions=dimensions(run_id),
            StartTime=datetime.now(timezone.utc) - timedelta(minutes=10),
            EndTime=datetime.now(timezone.utc) + timedelta(minutes=10),
            Period=60,
            Statistics=["Sum"],
        )
        points = res.get("Datapoints") or []
        if points:
            return sum(point["Sum"] for point in points)
        time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# 通知の経路（人向け＝SNS / 機械向け＝EventBridge）
# ---------------------------------------------------------------------------


def _allow_service(resource_arn: str, service: str, source_arn: str, sid: str) -> dict:
    """送り手を**名指しで**許可する（サービス名だけでは他の送り手も入れる）。"""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": sid,
                "Effect": "Allow",
                "Principal": {"Service": service},
                "Action": "sqs:SendMessage",
                "Resource": resource_arn,
                "Condition": {"ArnEquals": {"aws:SourceArn": source_arn}},
            }
        ],
    }


def _queue_arn(sqs, queue_url: str) -> str:
    return sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]


def ensure_channels(*, sns=None, sqs=None, events=None) -> dict:
    """トピック・購読・ルール・ターゲットをそろえる（何度実行してもよい）。"""
    sns = sns or clients.aws("sns")
    sqs = sqs or clients.aws("sqs")
    events = events or clients.aws("events")

    topic_arn = sns.create_topic(Name=TOPIC_NAME)["TopicArn"]

    inbox_url = sqs.create_queue(QueueName=INBOX_QUEUE)["QueueUrl"]
    inbox_arn = _queue_arn(sqs, inbox_url)
    sqs.set_queue_attributes(
        QueueUrl=inbox_url,
        Attributes={
            "Policy": json.dumps(
                _allow_service(inbox_arn, "sns.amazonaws.com", topic_arn, "AllowThisTopicOnly")
            )
        },
    )
    # 演習で中身を読みたいので生のまま届かせる（既定は SNS の封筒に入って届く）
    sns.subscribe(
        TopicArn=topic_arn,
        Protocol="sqs",
        Endpoint=inbox_arn,
        Attributes={"RawMessageDelivery": "true"},
        ReturnSubscriptionArn=True,
    )

    action_url = sqs.create_queue(QueueName=ACTION_QUEUE)["QueueUrl"]
    action_arn = _queue_arn(sqs, action_url)
    rule_arn = events.put_rule(
        Name=RULE_NAME,
        EventBusName=BUS_NAME,
        State="ENABLED",
        Description="ガバナンス指標のしきい値超過を是正処理へ回す",
        EventPattern=json.dumps({"source": [EVENT_SOURCE], "detail-type": [DETAIL_TYPE]}),
    )["RuleArn"]
    sqs.set_queue_attributes(
        QueueUrl=action_url,
        Attributes={
            "Policy": json.dumps(
                _allow_service(action_arn, "events.amazonaws.com", rule_arn, "AllowThisRuleOnly")
            )
        },
    )
    events.put_targets(
        Rule=RULE_NAME,
        EventBusName=BUS_NAME,
        Targets=[{"Id": "governance-actions", "Arn": action_arn}],
    )
    return {
        "topicArn": topic_arn,
        "inboxUrl": inbox_url,
        "actionUrl": action_url,
        "ruleArn": rule_arn,
    }


def alert_payload(breach: dict, summary: dict, *, run_id: str) -> dict:
    """通知に載せる内容。**質問も回答も載せません。**

    通知は転送されます（メール・チャット・チケット）。本文を載せると、
    残さないと決めた場所へ本文が拡散します。載せるのは
    「どの指標が」「どれだけ」「母数は」「次に何を起動するか」だけです。
    """
    return {
        "runId": run_id,
        "metric": breach["metricName"],
        "value": breach["value"],
        "threshold": breach["threshold"],
        "window": {"total": summary["total"], "attempted": summary["attempted"]},
        "action": breach["action"],
        "logGroup": provenance.LOG_GROUP,
    }


def notify(found: list[dict], summary: dict, *, channels: dict, run_id: str,
           sns=None, events=None) -> int:
    """超過ぶんだけ通知する（超過が無ければ1通も出さない）。"""
    if not found:
        return 0
    sns = sns or clients.aws("sns")
    events = events or clients.aws("events")
    payloads = [alert_payload(breach, summary, run_id=run_id) for breach in found]
    for payload in payloads:
        sns.publish(
            TopicArn=channels["topicArn"],
            # SNS の Subject は ASCII のみ（日本語を入れると落ちる）
            Subject="governance-threshold-breached",
            Message=json.dumps(payload, ensure_ascii=False),
        )
    res = events.put_events(
        Entries=[
            {
                "Source": EVENT_SOURCE,
                "DetailType": DETAIL_TYPE,
                "EventBusName": BUS_NAME,
                "Detail": json.dumps(payload, ensure_ascii=False),
            }
            for payload in payloads
        ]
    )
    if res.get("FailedEntryCount"):
        raise RuntimeError(f"イベントの投入に失敗しました: {res['Entries']}")
    return len(payloads)


def drain(queue_url: str, *, sqs=None, rounds: int = 5) -> int:
    """前の実行で残った通知を捨てる（演習を同じ状態から始めるため）。"""
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
                {"Id": str(index), "ReceiptHandle": message["ReceiptHandle"]}
                for index, message in enumerate(messages)
            ],
        )
        removed += len(messages)
    return removed


def receive(queue_url: str, *, expected: int, timeout: float = 40.0, sqs=None) -> list[dict]:
    sqs = sqs or clients.aws("sqs")
    deadline = time.monotonic() + timeout
    collected: list[dict] = []
    while len(collected) < expected and time.monotonic() < deadline:
        res = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=2
        )
        collected.extend(res.get("Messages") or [])
    return collected


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    state = provenance.bootstrap()
    logs = clients.aws("logs")
    run_id = provenance.new_run_id()
    entries = provenance.run_all(
        run_id=run_id, s3=state["s3"], ddb=state["ddb"], logs=logs
    )

    print(f"=== 1. 説明責任ログを数える（run={run_id}） ===")
    summary = aggregate(entries)
    print(f"  全件 {summary['total']} / 入口を通った件 {summary['attempted']}")
    for outcome in provenance.OUTCOMES:
        print(f"    {outcome:<12} {summary[outcome]} 件")
    print(f"  拒否率       {summary['blockedRate']}（分母 {summary['total']}）")
    print(f"  引用ゼロ率   {summary['zeroCitationRate']}（分母 {summary['attempted']}）")
    print(f"  exhausted率  {summary['exhaustedRate']}（分母 {summary['attempted']}）")

    print()
    print("=== 2. カスタムメトリクスに出して読み戻す ===")
    cw = clients.aws("cloudwatch")
    published = publish_metrics(cw, summary, run_id=run_id)
    print(f"  書いたメトリクス: {sorted(published)}")
    print(f"  読み戻したメトリクス: {listed_metrics(cw, run_id=run_id)}")
    print(f"  母数の合計: {read_count_metric(cw, run_id=run_id)}")

    print()
    print("=== 3. しきい値を超えた項目だけ通知する ===")
    channels = ensure_channels()
    drain(channels["inboxUrl"])
    drain(channels["actionUrl"])
    found = breaches(summary)
    for breach in found:
        print(
            f"  超過: {breach['metricName']} {breach['value']}"
            f" > {breach['threshold']} → {breach['action']}"
        )
    sent = notify(found, summary, channels=channels, run_id=run_id)
    print(f"  通知: {sent} 件（人向け SNS ＋ 機械向け EventBridge）")

    print()
    print("=== 4. 届いたことを確かめる ===")
    inbox = receive(channels["inboxUrl"], expected=sent)
    actions = receive(channels["actionUrl"], expected=sent)
    print(f"  SNS 経由: {len(inbox)} 件")
    for message in inbox:
        payload = json.loads(message["Body"])
        print(f"    {payload['metric']} value={payload['value']} action={payload['action']}")
    print(f"  EventBridge 経由: {len(actions)} 件")
    for message in actions:
        envelope = json.loads(message["Body"])
        print(f"    detail-type={envelope.get('detail-type')}"
              f" action={envelope.get('detail', {}).get('action')}")
    print("  ※ 通知に質問と回答は入っていません（転送されても本文は漏れません）")


if __name__ == "__main__":
    main()
