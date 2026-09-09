#!/usr/bin/env python3
"""セッション10: 3つの届け方（同期・非同期・ストリーミング）と相関 ID の伝播。

    docker compose exec app python src/session10/delivery.py

同じ質問を3通りで届けます。**答えは同じで、待たせ方だけが違う**ことを確かめます。

| 届け方 | 呼び出し側 | 実装（本書） | 実務 |
| :--- | :--- | :--- | :--- |
| 同期 | 完成まで待つ | Converse を1回 | API Gateway → Lambda → Bedrock |
| 非同期 | 受付 ID を即受け取り、後で取りに行く | SQS ＋ DynamoDB | API Gateway → SQS → Lambda → DynamoDB |
| ストリーミング | 差分を受け取りながら描画 | ConverseStream を標準出力へ | API Gateway WebSocket / Lambda の応答ストリーミング |

**サンドボックスの制約**: LocalStack Community に API Gateway・Lambda・AWS X-Ray は
ありません。そこで「境界をまたいだ追跡」は、相関 ID（trace ID）を SQS の
メッセージ属性で引き継ぎ、区間（span）ごとの所要時間を CloudWatch Logs へ
構造化ログとして残す形で再現します。実務ではこれを X-Ray が自動で行い、
サービスマップとして可視化します。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import model_router  # noqa: E402
import poc_probe  # noqa: E402
import streaming  # noqa: E402

JOB_QUEUE = "aip-c01-api-jobs"
JOB_TABLE = "aip_c01_api_jobs"
LOG_GROUP = "/sample-shoji/helpdesk/api-trace"

# 相関 ID を運ぶメッセージ属性の名前。実務の HTTP では X-Amzn-Trace-Id 相当
TRACE_ATTRIBUTE = "traceId"


# ---------------------------------------------------------------------------
# 相関 ID と区間（AWS X-Ray のトレース・セグメントの代替）
# ---------------------------------------------------------------------------


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class Trace:
    """1つのリクエストに対応する追跡単位。

    X-Ray でいうトレースです。`span` で囲んだ区間ごとに所要時間を記録します。
    **境界を越えるときは trace_id を引き継ぐ**のが要点で、これを忘れると
    「入口では 200 を返しているのに利用者は結果を受け取れていない」ときに
    入口側と処理側のログを突き合わせられません。
    """

    def __init__(self, mode: str, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or new_trace_id()
        self.mode = mode
        self.spans: list[dict] = []

    @contextmanager
    def span(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.spans.append(
                {"name": name, "ms": round((time.perf_counter() - started) * 1000, 1)}
            )

    def total_ms(self) -> float:
        return round(sum(span["ms"] for span in self.spans), 1)


def stream_name(trace_id: str) -> str:
    """1トレース = 1ストリーム。入口と処理側の記録が同じ場所に並ぶ。"""
    return f"trace/{trace_id}"


def _ignore_exists(func, **kwargs) -> None:
    try:
        func(**kwargs)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise


def emit(logs, trace: Trace, stage: str, **fields) -> dict:
    """構造化ログを1行残す。本文（質問・回答）は入れない（セッション6の方針）。"""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "traceId": trace.trace_id,
        "mode": trace.mode,
        "stage": stage,
        "spans": list(trace.spans),
        "totalMs": trace.total_ms(),
        **fields,
    }
    stream = stream_name(trace.trace_id)
    _ignore_exists(logs.create_log_stream, logGroupName=LOG_GROUP, logStreamName=stream)
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


def read_trace(logs, trace_id: str) -> list[dict]:
    """1トレース分の記録を読み戻す（X-Ray のトレース詳細に相当）。"""
    response = logs.get_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=stream_name(trace_id),
        startFromHead=True,
    )
    return [json.loads(event["message"]) for event in response["events"]]


# ---------------------------------------------------------------------------
# インフラの用意
# ---------------------------------------------------------------------------


def _endpoint_queue_url(queue_url: str) -> str:
    """（セッション8と同じ理由）LocalStack が返すホスト名はコンテナ内から解決できない。"""
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        return queue_url
    return f"{endpoint.rstrip('/')}{urllib.parse.urlparse(queue_url).path}"


def ensure_infra() -> tuple[object, object, object, str]:
    """ジョブキュー・ジョブ表・ロググループを冪等に用意する。"""
    sqs = clients.aws("sqs")
    ddb = clients.aws("dynamodb")
    logs = clients.aws("logs")

    created = sqs.create_queue(QueueName=JOB_QUEUE)["QueueUrl"]
    queue_url = _endpoint_queue_url(created)
    try:
        sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    except ClientError:
        queue_url = created

    try:
        ddb.create_table(
            TableName=JOB_TABLE,
            KeySchema=[{"AttributeName": "jobId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "jobId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=JOB_TABLE)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise

    _ignore_exists(logs.create_log_group, logGroupName=LOG_GROUP)
    return sqs, ddb, logs, queue_url


def purge(sqs, queue_url: str, max_loops: int = 5) -> int:
    """前回の実行が残したメッセージを捨てる（何度でも同じ状態から始める）。"""
    removed = 0
    for _ in range(max_loops):
        messages = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0
        ).get("Messages", [])
        if not messages:
            break
        for message in messages:
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# 1. 同期
# ---------------------------------------------------------------------------


def serve_sync(request: dict, router, *, infra=None) -> dict:
    """完成するまで待たせる。人が待っていて、答えが短いときの既定。"""
    sqs, ddb, logs, queue_url = infra or ensure_infra()
    trace = Trace("sync")
    with trace.span("bedrock"):
        result = router.invoke(request["question"], context=request.get("context"))
    emit(
        logs,
        trace,
        "responded",
        modelId=result["modelId"],
        outputTokens=result["outputTokens"],
        reportedLatencyMs=result["latencyMs"],
    )
    return {"mode": "sync", "traceId": trace.trace_id, "text": result["text"],
            "modelId": result["modelId"], "spans": trace.spans}


# ---------------------------------------------------------------------------
# 2. 非同期（受付だけして即座に返す）
# ---------------------------------------------------------------------------


def submit(request: dict, *, infra=None) -> dict:
    """受付 ID を返すところまで。**ここでモデルは1回も呼ばない。**

    実務では API Gateway が 202 Accepted と `jobId` を返し、
    利用者は後から `GET /jobs/{jobId}` で取りに来ます。
    """
    sqs, ddb, logs, queue_url = infra or ensure_infra()
    trace = Trace("async")
    job_id = uuid.uuid4().hex[:12]

    with trace.span("intake"):
        ddb.put_item(
            TableName=JOB_TABLE,
            Item={
                "jobId": {"S": job_id},
                "traceId": {"S": trace.trace_id},
                "status": {"S": "accepted"},
                "request": {"S": json.dumps(request, ensure_ascii=False)},
                "acceptedAt": {"N": str(int(time.time()))},
            },
        )
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"jobId": job_id, "request": request},
                                   ensure_ascii=False),
            # 相関 ID は本文ではなく属性に載せる。本文を開かない層
            # （DLQ・監視・フィルタ）からも読めるようにするため
            MessageAttributes={
                TRACE_ATTRIBUTE: {"DataType": "String",
                                  "StringValue": trace.trace_id}
            },
        )
    emit(logs, trace, "accepted", jobId=job_id)
    return {"mode": "async", "traceId": trace.trace_id, "jobId": job_id,
            "status": "accepted", "spans": trace.spans}


def work_off(router, *, infra=None, expected: int = 1, max_loops: int = 5) -> list[dict]:
    """キューから取り出して処理する（実務では Lambda のイベントソース）。

    削除は**処理が終わったあと**に行います。先に削除すると、処理中に
    落ちたメッセージが消えて取りこぼしに気づけません。
    """
    sqs, ddb, logs, queue_url = infra or ensure_infra()
    done: list[dict] = []
    for _ in range(max_loops):
        messages = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1,
            MessageAttributeNames=["All"],
        ).get("Messages", [])
        if not messages:
            if len(done) >= expected:
                break
            continue
        for message in messages:
            payload = json.loads(message["Body"])
            attributes = message.get("MessageAttributes") or {}
            inherited = (attributes.get(TRACE_ATTRIBUTE) or {}).get("StringValue")
            # 受付側と同じ trace_id で続ける。ここが「境界をまたぐ」場所
            trace = Trace("async", trace_id=inherited)
            request = payload["request"]
            with trace.span("bedrock"):
                result = router.invoke(
                    request["question"], context=request.get("context")
                )
            with trace.span("persist"):
                ddb.put_item(
                    TableName=JOB_TABLE,
                    Item={
                        "jobId": {"S": payload["jobId"]},
                        "traceId": {"S": trace.trace_id},
                        "status": {"S": "done"},
                        "answer": {"S": result["text"]},
                        "modelId": {"S": result["modelId"]},
                        "finishedAt": {"N": str(int(time.time()))},
                    },
                )
            emit(logs, trace, "worker", jobId=payload["jobId"],
                 modelId=result["modelId"])
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
            done.append({"jobId": payload["jobId"], "traceId": trace.trace_id,
                         "text": result["text"], "modelId": result["modelId"],
                         "spans": trace.spans})
        if len(done) >= expected:
            break
    return done


def get_job(job_id: str, *, ddb=None) -> dict | None:
    """利用者が後から取りに来る口（`GET /jobs/{jobId}` 相当）。"""
    ddb = ddb or clients.aws("dynamodb")
    item = ddb.get_item(TableName=JOB_TABLE, Key={"jobId": {"S": job_id}}).get("Item")
    if not item:
        return None
    return {key: (value.get("S") or value.get("N")) for key, value in item.items()}


# ---------------------------------------------------------------------------
# 3. ストリーミング
# ---------------------------------------------------------------------------


def serve_stream(request: dict, runtime, *, infra=None, on_delta=None) -> dict:
    """差分を流す。人が待っていて、答えが長いときの既定。"""
    sqs, ddb, logs, queue_url = infra or ensure_infra()
    trace = Trace("stream")
    with trace.span("stream"):
        streamed = streaming.stream_answer(
            runtime,
            request["question"],
            request.get("context"),
            on_delta=on_delta,
        )
    emit(
        logs,
        trace,
        "streamed",
        modelId=streamed["modelId"],
        outputTokens=streamed["usage"]["outputTokens"],
        firstDeltaMs=round(streamed["firstDeltaMs"], 1),
        deltas=len(streamed["deltas"]),
    )
    return {"mode": "stream", "traceId": trace.trace_id, "text": streamed["text"],
            "modelId": streamed["modelId"], "firstDeltaMs": streamed["firstDeltaMs"],
            "totalMs": streamed["totalMs"], "spans": trace.spans}


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    model_router.reset_mock()
    infra = ensure_infra()
    sqs, ddb, logs, queue_url = infra
    purge(sqs, queue_url)
    router = model_router.ModelRouter(config=model_router.bootstrap())
    runtime = clients.bedrock_runtime()

    question, source = poc_probe.QUESTIONS[0]
    request = {"question": question, "context": source}

    print("=== 1. 同期 ===")
    sync = serve_sync(request, router, infra=infra)
    print(f"traceId={sync['traceId']} / spans={sync['spans']}")

    print()
    print("=== 2. 非同期（受付 → 後で取りに行く） ===")
    accepted = submit(request, infra=infra)
    print(f"jobId={accepted['jobId']} / status={accepted['status']}")
    print(f"受付時点の呼び出し数: {model_router.mock_usage()['calls']}回"
          "（同期の1回だけ。受付ではモデルを呼んでいません）")
    processed = work_off(router, infra=infra, expected=1)
    stored = get_job(accepted["jobId"], ddb=ddb)
    print(f"処理後の status={stored['status']} / modelId={stored['modelId']}")

    print()
    print("=== 3. ストリーミング ===")
    streamed = serve_stream(request, runtime, infra=infra)
    print(f"初回差分まで {streamed['firstDeltaMs']:.1f} ms / "
          f"完了まで {streamed['totalMs']:.1f} ms")

    print()
    print("=== 4. 答えは同じ。待たせ方だけが違う ===")
    same = sync["text"] == processed[0]["text"] == streamed["text"]
    print(f"3経路の本文が一致: {same}")

    print()
    print("=== 5. 境界をまたいだ追跡（X-Ray の代替） ===")
    for record in read_trace(logs, accepted["traceId"]):
        print(f"  {record['stage']:<9} traceId={record['traceId']}"
              f" spans={record['spans']}")
    print("受付（accepted）と処理（worker）が同じ traceId で並びます。")

    model_router.reset_mock()


if __name__ == "__main__":
    main()
