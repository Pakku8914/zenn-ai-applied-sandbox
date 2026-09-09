#!/usr/bin/env python3
"""セッション9: 非同期の受け口（実務のバッチ推論の代替）。

    docker compose exec app python src/session09/batch_intake.py

実務で「今すぐ答えなくてよい大量の処理」を流すときは、Amazon Bedrock の
バッチ推論（`CreateModelInvocationJob`）に S3 の JSONL を渡します。
LocalStack Community には Bedrock も SageMaker も無いため、本書では
**SQS を受け口にして、取り出したぶんをオンデマンドで処理する**形に置き換えます。

置き換えても学べることは同じです。すなわち
「呼び出し側は結果を待たない」「順序は保証されない」「取りこぼしは可視化できる」。
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session09")

from awskit import clients  # noqa: E402

import cascade  # noqa: E402
import model_router  # noqa: E402

QUEUE_NAME = "aip-c01-batch-intake"


def queue_url(sqs) -> str:
    """キューを用意する。`create_queue` は同名なら既存の URL を返す（冪等）。"""
    return sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]


def clear(sqs, url: str, max_loops: int = 5) -> int:
    """前回の実行が残したメッセージを捨てる（演習を何度でも同じ状態から始める）。"""
    removed = 0
    for _ in range(max_loops):
        received = sqs.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=0
        ).get("Messages", [])
        if not received:
            break
        for message in received:
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
            removed += 1
    return removed


def enqueue(sqs, url: str, records: list[dict]) -> int:
    """受け付けだけして即座に返す。ここでモデルは呼ばない。"""
    sent = 0
    for start in range(0, len(records), 10):  # SendMessageBatch は1回10件まで
        entries = [
            {"Id": r["requestId"], "MessageBody": json.dumps(r, ensure_ascii=False)}
            for r in records[start : start + 10]
        ]
        response = sqs.send_message_batch(QueueUrl=url, Entries=entries)
        sent += len(response.get("Successful", []))
    return sent


def drain(sqs, url: str, router, expected: int, max_loops: int = 8) -> list[dict]:
    """取り出したぶんをカスケードで処理する。

    削除は**処理が成功したあと**に行います。先に削除すると、処理中に落ちた
    メッセージが消えてしまい、取りこぼしに気づけません。
    """
    done: list[dict] = []
    for _ in range(max_loops):
        received = sqs.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        ).get("Messages", [])
        if not received:
            if len(done) >= expected:
                break
            continue
        for message in received:
            record = json.loads(message["Body"])
            done.append(cascade.run_one(record, router))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
        if len(done) >= expected:
            break
    return done


def main() -> None:
    model_router.reset_mock()
    sqs = clients.aws("sqs")
    url = queue_url(sqs)
    router = model_router.ModelRouter()

    print("=== 1. 受け付け（同期では待たない） ===")
    print(f"キュー: {QUEUE_NAME}")
    print(f"前回の残りを削除: {clear(sqs, url)}件")
    sent = enqueue(sqs, url, cascade.WORKLOAD)
    print(f"投入: {sent}件（この時点でモデルは1回も呼んでいません）")

    print()
    print("=== 2. 取り出して処理する ===")
    done = drain(sqs, url, router, expected=sent)
    print(f"処理: {len(done)}件")
    paths: dict[str, int] = {}
    for d in done:
        paths[d["path"]] = paths.get(d["path"], 0) + 1
    for path in sorted(paths):
        print(f"  {path:<12} {paths[path]}件")
    print("同期実行と同じ経路になります（受け口を変えても判断は変わりません）")

    left = sqs.receive_message(
        QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=1
    ).get("Messages", [])
    print(f"判定 キューが空になった : {'OK' if not left else 'NG'}")

    usage = model_router.mock_usage()
    print()
    print("=== 3. 会計 ===")
    print(f"[実測] 呼び出し {usage['calls']}回 / "
          f"推定コスト {usage['estimatedUsdTotal']:.6f} USD")
    print("実務ではここをバッチ推論ジョブ（CreateModelInvocationJob）に置き換えます。")
    print("バッチはオンデマンドより安い枠が用意される一方、完了まで待てる用途に限られます。")

    model_router.reset_mock()


if __name__ == "__main__":
    main()
