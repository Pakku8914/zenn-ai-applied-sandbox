#!/usr/bin/env python3
"""セッション3: 取り込みバッチの検証 → 隔離パイプライン。

社内文書のバッチ（正常12件＋壊れた6件）を `input_guard.check_all()` に通し、

* 受理したものは件数と修復内容を集計する
* 遮断したものは **隔離ストア（S3）に検知結果だけを書き** 、
  **再処理キュー（SQS）に1通ずつ流す**
* 隔離率がしきい値を超えたらアラート対象として報告する

を行います。実務ではこの判定を AWS Glue Data Quality のルールセットに寄せ、
結果の配線（S3 への隔離・SQS への再処理依頼・CloudWatch へのメトリクス）を
Lambda か Step Functions で組みます。ここでは配線の形だけを最小構成で作ります。

    docker compose exec app python src/session03/ingest_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session03")

from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import input_guard  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "kb_corpus.json"

QUARANTINE_BUCKET = "sample-shoji-quarantine"
QUARANTINE_QUEUE = "aip-c01-quarantine"

# バッチ全体の健全性のしきい値。1件の欠陥は正常だが、
# 「1割が落ちる」は取り込み経路そのものが壊れているサインなのでアラートにする
ALERT_QUARANTINE_RATIO = 0.10

# 半角数字を全角に写す変換表（重複レコードを機械的に作るために使う）
TO_FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")

INBOX = "s3://sample-shoji-docs/inbox"


def load_good_records() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def build_broken_records(good: list[dict]) -> list[dict]:
    """現場で実際に来る壊れ方を6通り再現する。"""
    hr_001 = next(d for d in good if d["id"] == "hr-001")
    return [
        # 本文が空（テンプレートだけ登録された文書・抽出に失敗した PDF）
        {"id": "bad-001", "uri": f"{INBOX}/bad-001.md", "text": "　　 "},
        # 長すぎる（議事録を1ファイルに連結したもの）
        {"id": "bad-002", "uri": f"{INBOX}/bad-002.md", "text": "あ" * 20_000},
        # 機密混入（問い合わせ対応履歴をそのまま貼った文書）
        {
            "id": "bad-003",
            "uri": f"{INBOX}/bad-003.md",
            "text": (
                "顧客の田中様（tanaka@example.com、090-1234-5678）から、"
                "契約番号 123456789012 の照会を受けました。"
            ),
        },
        # 全角英数（表計算ソフトからのコピー）。これは修復して通す
        {
            "id": "bad-004",
            "uri": f"{INBOX}/bad-004.md",
            "text": "ＶＰＮクライアントはＷｉｎｄｏｗｓ１１で動作しますか。",
        },
        # 正規化すると既存文書と一致する重複（全角数字と全角空白だけが違うコピー）
        {
            "id": "bad-005",
            "uri": f"{INBOX}/bad-005.md",
            "text": "　" + hr_001["text"].translate(TO_FULLWIDTH) + "　",
        },
        # 文字化け（Shift_JIS のファイルを UTF-8 として読んだ結果）
        {
            "id": "bad-006",
            "uri": f"{INBOX}/bad-006.md",
            "text": "貸与PCの交換申��は資産管理番号が必要です。",
        },
    ]


def load_records() -> list[dict]:
    good = load_good_records()
    return good + build_broken_records(good)


# ---------------------------------------------------------------------------
# 隔離先（S3 / SQS）の準備
# ---------------------------------------------------------------------------


def _s3():
    kwargs: dict = {}
    if os.environ.get("AWS_ENDPOINT_URL"):
        # LocalStack のようなカスタムエンドポイントでは
        # `バケット名.ホスト名` の仮想ホスト形式を名前解決できないため path 形式にする
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return clients.aws("s3", **kwargs)


def _endpoint_queue_url(queue_url: str) -> str:
    """キュー URL のホストを、クライアントのエンドポイントに合わせる。

    LocalStack は既定で `sqs.us-east-1.localhost.localstack.cloud` を含む URL を返します。
    このホストは 127.0.0.1 に解決されるため、コンテナ内から叩くと自分自身に接続してしまいます。
    実 AWS では `AWS_ENDPOINT_URL` が未設定なので、この関数は何もしません。
    """
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        return queue_url
    return f"{endpoint.rstrip('/')}{urllib.parse.urlparse(queue_url).path}"


def _reachable_queue_url(sqs, created: str) -> str:
    """到達できるキュー URL を返す。

    ホストを差し替えた版を優先しますが、環境によっては元の URL のままで
    問題ないため、差し替えた版で属性取得に失敗したら元に戻します。
    """
    candidate = _endpoint_queue_url(created)
    if candidate == created:
        return created
    try:
        sqs.get_queue_attributes(QueueUrl=candidate, AttributeNames=["QueueArn"])
    except Exception:  # noqa: BLE001 — 到達可否の判定なので例外の種類は問わない
        return created
    return candidate


def ensure_resources() -> tuple[object, object, str]:
    """隔離バケットと再処理キューを冪等に用意し、(s3, sqs, queue_url) を返す。"""
    s3 = _s3()
    sqs = clients.aws("sqs")
    try:
        s3.create_bucket(Bucket=QUARANTINE_BUCKET)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
    created = sqs.create_queue(QueueName=QUARANTINE_QUEUE)["QueueUrl"]
    return s3, sqs, _reachable_queue_url(sqs, created)


def quarantine_payload(result: input_guard.CheckResult, run_id: str) -> dict:
    """隔離レコード。**本文を入れない**のが設計上の要点。

    原本は取り込み元のバケットに残っているので、隔離側には所在（URI）と
    検知内容だけを置きます。本文をコピーすると、機密を含むデータを
    別のバケットへ増殖させてしまい、削除依頼にも応えられなくなります。
    """
    return {
        "runId": run_id,
        "docId": result.doc_id,
        "sourceUri": result.source_uri,
        "rules": list(result.rules),
        "details": list(result.details),
        "tokens": result.tokens,
        "detectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def run(run_id: str | None = None) -> dict:
    """検証 → 隔離を1バッチ分実行し、集計を返す。"""
    run_id = run_id or uuid.uuid4().hex[:8]
    s3, sqs, queue_url = ensure_resources()

    records = load_records()
    results = input_guard.check_all(records)

    by_rule: dict[str, int] = {}
    quarantined = 0
    for result in results:
        if result.status != "quarantined":
            continue
        quarantined += 1
        for rule in result.rules:
            by_rule[rule] = by_rule.get(rule, 0) + 1
        payload = quarantine_payload(result, run_id)
        body = json.dumps(payload, ensure_ascii=False)
        s3.put_object(
            Bucket=QUARANTINE_BUCKET,
            Key=f"quarantine/{run_id}/{result.doc_id}.json",
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        sqs.send_message(QueueUrl=queue_url, MessageBody=body)

    accepted = [r for r in results if r.status == "accepted"]
    ratio = round(quarantined / len(results), 3) if results else 0.0
    return {
        "runId": run_id,
        "total": len(results),
        "accepted": len(accepted),
        "repaired": sum(1 for r in accepted if r.repairs),
        "quarantined": quarantined,
        "byRule": by_rule,
        "quarantineRate": ratio,
        "alert": ratio > ALERT_QUARANTINE_RATIO,
        "queueUrl": queue_url,
        "prefix": f"quarantine/{run_id}/",
    }


def main() -> None:
    summary = run()
    print("=== 取り込みバッチの検証結果 ===")
    print(f"  runId        : {summary['runId']}")
    print(f"  入力         : {summary['total']} 件")
    print(f"  受理         : {summary['accepted']} 件（うち修復 {summary['repaired']} 件）")
    print(f"  隔離         : {summary['quarantined']} 件")
    print(f"  隔離率       : {summary['quarantineRate']:.1%}")
    for rule in input_guard.BLOCK_RULES:
        print(f"    - {rule:<10}: {summary['byRule'].get(rule, 0)} 件")
    print(f"  アラート     : {'発火' if summary['alert'] else 'なし'}"
          f"（しきい値 {ALERT_QUARANTINE_RATIO:.0%}）")
    print()
    print(f"  隔離ストア   : s3://{QUARANTINE_BUCKET}/{summary['prefix']}")
    print(f"  再処理キュー : {summary['queueUrl']}")


if __name__ == "__main__":
    main()
