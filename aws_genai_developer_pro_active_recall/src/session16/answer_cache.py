#!/usr/bin/env python3
"""セッション16: 同じ答えを二度作らないための2種のキャッシュ。

* 完全一致キャッシュ … 「同じ答えになる条件」をすべて含めたキーの一致で返す
* セマンティックキャッシュ … 埋め込みの近さで「同じ質問」と見なして返す

置き場は Amazon DynamoDB です。**実務では Amazon ElastiCache（Redis / Valkey）や
DynamoDB Accelerator（DAX）を使います**（ミリ秒未満で引けること、TTL の扱いが
軽いことが理由）。LocalStack Community には ElastiCache が無いため、本書は
DynamoDB で仕組みだけを再現します。API の形は違っても「キーに何を含めるか」
「いつ捨てるか」の判断は同じです。

セマンティックキャッシュのベクトルはプロセス内に持ちます。実務では
OpenSearch や pgvector（セッション4・5で作った索引）に載せます。
埋め込みの生成はセッション4の `vector_store.embed_text` を再利用します
（キャッシュのためだけに別の埋め込み経路を作ると、索引とキャッシュで
別のベクトル空間ができてしまいます）。
"""

from __future__ import annotations

import hashlib
import math
import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import vector_store  # noqa: E402

TABLE_NAME = "aip_c01_answer_cache"

# キャッシュの寿命。短いほど陳腐化の危険が小さく、長いほど当たりやすい。
# 「答えが変わりうる間隔」で決める値で、性能から決める値ではない
TTL_SECONDS = 900

EMBED_MODEL_ID = vector_store.EMBED_MODEL_ID


# ---------------------------------------------------------------------------
# 完全一致キャッシュ（置き場: DynamoDB）
# ---------------------------------------------------------------------------


def ensure_table(ddb=None):
    """キャッシュ表を冪等に用意する。"""
    ddb = ddb or clients.aws("dynamodb")
    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "cacheKey", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "cacheKey", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
    try:
        # 捨てる仕組みはアプリのロジックではなくデータストアの機能に寄せる
        ddb.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
    except ClientError:
        # すでに有効なら ValidationException になる。冪等に扱う
        pass
    return ddb


def cache_key(*, model_id: str, prompt_version: str, system: str, user_text: str) -> str:
    """キャッシュキーを作る。

    **「答えが変わる条件」をすべてキーに含める**のが原則です。モデル ID を
    忘れると別モデルの答えを返し、プロンプトの版を忘れると版を上げたのに
    古い文面の答えを返し続けます（セッション6で版を管理した理由がここで効きます）。
    利用者の識別子を含めるかは別の判断で、含めなければ他人の答えが混ざる
    危険があり、含めればヒット率が落ちます。
    """
    material = "\x1f".join([model_id, prompt_version, system, user_text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get(ddb, key: str, *, now: float | None = None) -> dict | None:
    """キャッシュを引く。期限切れはヒットにしない。"""
    item = ddb.get_item(TableName=TABLE_NAME, Key={"cacheKey": {"S": key}}).get("Item")
    if not item:
        return None
    stamp = time.time() if now is None else now
    if int(item["expiresAt"]["N"]) <= stamp:
        # DynamoDB の TTL による削除は即時ではない（実 AWS では最大48時間遅れる）。
        # 読み出し側でも期限を確認するのが安全側の実装
        return None
    return {"question": item["question"]["S"], "answer": item["answer"]["S"],
            "outputTokens": int(item["outputTokens"]["N"])}


def put(
    ddb,
    key: str,
    *,
    question: str,
    answer: str,
    output_tokens: int,
    ttl_seconds: int = TTL_SECONDS,
) -> None:
    """答えを保存する。質問の本文は残さない選択もあり得る（セッション13・14）。"""
    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "cacheKey": {"S": key},
            "question": {"S": question},
            "answer": {"S": answer},
            # 低レベル API では数値も文字列で渡す（int を渡すと ParamValidationError）
            "outputTokens": {"N": str(output_tokens)},
            "expiresAt": {"N": str(int(time.time()) + ttl_seconds)},
        },
    )


def clear(ddb) -> int:
    """表を空にする（演習を何度実行しても同じ状態から始めるため）。"""
    removed = 0
    scan = ddb.scan(TableName=TABLE_NAME, ProjectionExpression="cacheKey")
    for item in scan.get("Items", []):
        ddb.delete_item(TableName=TABLE_NAME, Key={"cacheKey": item["cacheKey"]})
        removed += 1
    return removed


def count(ddb) -> int:
    return int(ddb.scan(TableName=TABLE_NAME, Select="COUNT")["Count"])


# ---------------------------------------------------------------------------
# セマンティックキャッシュ（キーは埋め込み）
# ---------------------------------------------------------------------------


def cosine(a: list[float], b: list[float]) -> float:
    """コサイン類似度（セッション5と同じ指標）。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return round(dot / (na * nb), 6)


class SemanticCache:
    """埋め込みの近さで「同じ質問」と見なすキャッシュ。

    完全一致キャッシュとの違いは1点だけです。**キーが一致ではなく距離**である
    ことです。そのため「当たらないはずのものが当たる」（誤ヒット）が起こり得ます。
    しきい値は精度ではなく、**間違ってヒットしたときの損害**で決めます。
    """

    def __init__(self, runtime, *, threshold: float) -> None:
        self._runtime = runtime
        self.threshold = threshold
        self._entries: list[dict] = []
        self.embed_calls = 0

    def embed(self, question: str) -> list[float]:
        self.embed_calls += 1
        return vector_store.embed_text(self._runtime, question)

    def nearest(self, vector: list[float]) -> tuple[dict | None, float]:
        """最も近い項目と、その類似度を返す。空なら (None, -1.0)。"""
        best: dict | None = None
        score = -1.0
        for entry in self._entries:
            candidate = cosine(vector, entry["vector"])
            if candidate > score:
                best, score = entry, candidate
        return best, score

    def lookup(self, question: str) -> dict:
        """問い合わせを1件引く。**引くだけで埋め込みの費用が発生します。**"""
        vector = self.embed(question)
        entry, score = self.nearest(vector)
        hit = entry is not None and score >= self.threshold
        return {"hit": hit, "score": score, "entry": entry, "vector": vector}

    def put(
        self, question: str, answer: str, *, vector: list[float] | None = None
    ) -> None:
        """答えを登録する。`lookup` で作ったベクトルを渡せば埋め込みは1回で済む。"""
        self._entries.append(
            {
                "question": question,
                "answer": answer,
                "vector": vector if vector is not None else self.embed(question),
            }
        )

    def size(self) -> int:
        return len(self._entries)
