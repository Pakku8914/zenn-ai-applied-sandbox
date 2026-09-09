#!/usr/bin/env python3
"""セッション14: データリネージの台帳（どの文書のどの版が根拠だったか）。

    docker compose exec app python src/session14/lineage.py

実務では **AWS Glue** のジョブが取り込みを行い、**AWS Glue Data Catalog** が
「どこに何があるか（テーブル・列・パーティション・プロパティ）」を持ちます。
LocalStack Community に Glue はないため、同じ役割を DynamoDB の1表で作ります。

    Glue Data Catalog のテーブル定義      → 台帳の1行（在り処・版・所管）
    Glue ジョブの実行履歴                → 行の ingestedAt / pipelineRunId
    Lake Formation・メタデータタグ        → 行の owner / classification

**台帳に本文は入れません。** 入れると原本の複製ができ、更新と削除を二重に
管理することになります（セッション3で隔離バケットに本文を複製しなかったのと
同じ判断です）。残すのは「在り処（URI）」「版（更新日 ＋ 本文のハッシュ）」
「所管」だけです。

台帳の主キーは (sourceUri, revision) です。**版は上書きせず積み上げます。**
文書が改訂されても、過去の回答が根拠にした版をそのまま引けるようにするためです。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import vector_store  # noqa: E402  セッション4（コーパスの読み込みと本文ハッシュ）

TABLE = "aip_c01_doc_lineage"

# 文書の所管部門。**「誰に聞けば直せるか」が分からない資料は根拠に使えません。**
OWNERS = {
    "IT": "情報システム部",
    "経費": "経理部",
    "人事": "人事部",
    "セキュリティ": "情報システム部",
}

# 格付けはメタデータタグとして持つだけにします。
# 値の決め方（4段階の基準・匿名化の要否）はセッション13の範囲です。
CLASSIFICATION = "社内限定"

# 台帳に載せる属性。**ここに本文（text / content）を足さないこと。**
FIELDS = (
    "sourceUri",
    "revision",
    "docId",
    "title",
    "category",
    "updatedAt",
    "contentHash",
    "owner",
    "classification",
    "ingestedAt",
    "pipelineRunId",
)

# 改訂の演習で使う差し替え内容（何度実行しても同じ版になるよう固定する）
REVISED_URI = "s3://sample-shoji-docs/hr/paid-leave.md"
REVISED_AT = "2026-09-05"
REVISED_TEXT = (
    "年次有給休暇は入社6か月経過時点で10日付与され、以降は毎年4月1日に付与されます。"
    "未消化分は翌年度に限り繰り越せますが、繰越上限は25日です。"
)


def revision_of(updated_at: str, content_hash: str) -> str:
    """版の名前。**更新日を先に置く**ので、辞書順の最後が最新版になる。

    ハッシュだけでは新旧が分からず、更新日だけでは同じ日の差し替えを区別できません。
    2つを組み合わせると「順序が分かり、内容が変われば必ず別名になる」版になります。
    """
    return f"{updated_at}#{content_hash[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_table(ddb=None):
    ddb = ddb or clients.aws("dynamodb")
    try:
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "sourceUri", "KeyType": "HASH"},
                {"AttributeName": "revision", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "sourceUri", "AttributeType": "S"},
                {"AttributeName": "revision", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
    return ddb


def rows_from_corpus() -> list[dict]:
    """取り込み元（`fixtures/kb_corpus.json`）から台帳の行を作る。

    セッション4の `load_chunks` と `content_hash` をそのまま使います。
    **リネージの起点は検索層の取り込み処理**であって、あとから別に作るものでは
    ありません。取り込みで計算したハッシュを、そのまま台帳の版名に使います。
    """
    rows: list[dict] = []
    for chunk in vector_store.load_chunks():
        digest = vector_store.content_hash(chunk["content"])
        rows.append(
            {
                "sourceUri": chunk["source_uri"],
                "revision": revision_of(chunk["updated_at"], digest),
                "docId": chunk["doc_id"],
                "title": chunk["title"],
                "category": chunk["category"],
                "updatedAt": chunk["updated_at"],
                "contentHash": digest,
                "owner": OWNERS[chunk["category"]],
                "classification": CLASSIFICATION,
            }
        )
    return rows


def _to_item(row: dict, *, pipeline_run_id: str) -> dict:
    item = {**row, "ingestedAt": _now_iso(), "pipelineRunId": pipeline_run_id}
    unknown = sorted(set(item) - set(FIELDS))
    if unknown:
        # 本文が紛れ込むのはここです。**気づける形にしておく。**
        raise ValueError(f"台帳に載せない属性が含まれています: {unknown}")
    return {key: {"S": str(value)} for key, value in item.items()}


def _from_item(item: dict) -> dict:
    return {key: value["S"] for key, value in item.items()}


def register(ddb, rows: list[dict], *, pipeline_run_id: str = "ingest-initial") -> int:
    """台帳に登録する。同じ版を何度登録しても行は増えない（キーが同じ）。"""
    for row in rows:
        ddb.put_item(TableName=TABLE, Item=_to_item(row, pipeline_run_id=pipeline_run_id))
    return len(rows)


def prune(ddb, rows: list[dict]) -> int:
    """取り込み元に無い版を台帳から消す（演習を同じ状態から始めるため）。

    運用では**消しません**（過去の回答の根拠が引けなくなる）。ここでは
    「改訂を1回だけ起こす」演習を何度も再現したいので、演習の前に掃除します。
    """
    keep = {(row["sourceUri"], row["revision"]) for row in rows}
    removed = 0
    for item in _scan_items(ddb):
        key = (item["sourceUri"], item["revision"])
        if key not in keep:
            ddb.delete_item(
                TableName=TABLE,
                Key={"sourceUri": {"S": key[0]}, "revision": {"S": key[1]}},
            )
            removed += 1
    return removed


def _scan_items(ddb) -> list[dict]:
    """台帳の全件走査。

    Scan は本番の要求経路では避けますが、**メタデータの棚卸し**（1日1回・
    数千件）には妥当です。要求ごとに引くのは `resolve` の Query 側です。
    """
    items: list[dict] = []
    kwargs: dict = {"TableName": TABLE}
    while True:
        res = ddb.scan(**kwargs)
        items.extend(_from_item(item) for item in res.get("Items", []))
        if "LastEvaluatedKey" not in res:
            return items
        kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]


def all_rows(ddb) -> list[dict]:
    """台帳の全行（棚卸し・モデルカードの材料に使う）。"""
    return _scan_items(ddb)


def count(ddb) -> int:
    return len(_scan_items(ddb))


def resolve(ddb, uri: str) -> dict | None:
    """URI から**そのときの最新版**を1件引く（回答時に版を固定するために使う）。"""
    res = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="#uri = :uri",
        ExpressionAttributeNames={"#uri": "sourceUri"},
        ExpressionAttributeValues={":uri": {"S": uri}},
        ScanIndexForward=False,  # 版名の辞書順の最後（＝最新）から返す
        Limit=1,
        ConsistentRead=True,
    )
    items = res.get("Items") or []
    return _from_item(items[0]) if items else None


def resolve_revision(ddb, uri: str, revision: str) -> dict | None:
    """**ログに残した版**を引く。文書が改訂されていても、当時の版が返る。"""
    res = ddb.get_item(
        TableName=TABLE,
        Key={"sourceUri": {"S": uri}, "revision": {"S": revision}},
        ConsistentRead=True,
    )
    item = res.get("Item")
    return _from_item(item) if item else None


def revisions(ddb, uri: str) -> list[str]:
    """1文書の版の一覧（新しい順）。"""
    res = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="#uri = :uri",
        ExpressionAttributeNames={"#uri": "sourceUri"},
        ExpressionAttributeValues={":uri": {"S": uri}},
        ScanIndexForward=False,
        ConsistentRead=True,
    )
    return [item["revision"]["S"] for item in res.get("Items", [])]


def revise(
    ddb,
    uri: str,
    *,
    text: str,
    updated_at: str,
    pipeline_run_id: str = "ingest-revised",
) -> dict:
    """文書の改訂を台帳に足す（**前の版は消さない**）。"""
    current = resolve(ddb, uri)
    if current is None:
        raise KeyError(f"台帳に無い文書です: {uri}")
    digest = vector_store.content_hash(text)
    row = {
        key: current[key]
        for key in ("sourceUri", "docId", "title", "category", "owner", "classification")
    }
    row.update(
        updatedAt=updated_at,
        contentHash=digest,
        revision=revision_of(updated_at, digest),
    )
    ddb.put_item(TableName=TABLE, Item=_to_item(row, pipeline_run_id=pipeline_run_id))
    return row


def bootstrap(ddb=None) -> dict:
    """台帳を取り込み元の状態にそろえる。"""
    ddb = ensure_table(ddb)
    rows = rows_from_corpus()
    removed = prune(ddb, rows)
    register(ddb, rows)
    return {"registered": len(rows), "removed": removed, "client": ddb}


def main() -> None:
    state = bootstrap()
    ddb = state["client"]
    print("=== 1. 取り込み元から台帳を作る ===")
    print(f"  登録: {state['registered']} 件 / 掃除した古い版: {state['removed']} 件")
    print(f"  台帳の行数: {count(ddb)}")

    print()
    print("=== 2. 引用の URI から出どころを引く ===")
    row = resolve(ddb, REVISED_URI)
    print(f"  {REVISED_URI}")
    print(
        f"    docId={row['docId']} title={row['title']}"
        f" updatedAt={row['updatedAt']} owner={row['owner']}"
    )
    print(f"    版名の形: 更新日#ハッシュ12桁（長さ {len(row['revision'])}）")
    pinned = row["revision"]

    print()
    print("=== 3. 文書を改訂する（前の版は消えない） ===")
    revise(ddb, REVISED_URI, text=REVISED_TEXT, updated_at=REVISED_AT)
    print(f"  版の一覧（新しい順・更新日だけ表示）:"
          f" {[rev.split('#')[0] for rev in revisions(ddb, REVISED_URI)]}")
    old = resolve_revision(ddb, REVISED_URI, pinned)
    print(f"  当時の版も引ける: updatedAt={old['updatedAt']} / 同じ版名か={old['revision'] == pinned}")

    print()
    print("=== 4. 台帳に本文は入っていない ===")
    print(f"  属性: {sorted(old)}")


if __name__ == "__main__":
    main()
