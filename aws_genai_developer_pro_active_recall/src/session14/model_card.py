#!/usr/bin/env python3
"""セッション14: モデルカード（この仕組みの説明書）をプログラムで作る。

    docker compose exec app python src/session14/model_card.py

実務では **Amazon SageMaker AI のモデルカード**を使い、`boto3` の
`sagemaker.create_model_card(ModelCardName=..., Content=..., ModelCardStatus=...)`
で JSON を投入します（Draft → PendingReview → Approved → Archived の状態を持ちます）。
LocalStack Community に SageMaker は無いため、ここでは**同じ内容の JSON を組み立て、
Amazon S3 に版として置き、必須項目の欠落を検出するチェッカー**を書きます。
実務で置き場が変わっても、「何を書くか」と「欠けたら公開しない」は同じです。

基盤モデル（FM）を使う側のカードで独特なのは、**自分では学習していない**点です。
学習データの説明は書けません。代わりに書くのは、出力を決めている実物です。

    どの FM の版か / どのプロンプトの版とハッシュか / どの資料の版を引くか
    どのガードレールの版か / 何を監視し、どの値で人を呼ぶか / 誰が承認し、いつ見直すか
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session14")

from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import lineage  # noqa: E402
import provenance  # noqa: E402

BUCKET = "sample-shoji-model-cards"
CARD_NAME = "helpdesk-assistant"
SCHEMA_VERSION = "2026-09-08"

# SageMaker AI のモデルカードと同じ語彙にそろえておく（移すときに迷わない）
STATUSES = ("Draft", "PendingReview", "Approved", "Archived")
RISK_RATINGS = ("Low", "Medium", "High", "Unknown")

# **1つでも空なら公開しない**項目。ドット記法で入れ子を指す
REQUIRED_PATHS = (
    "modelOverview.name",
    "modelOverview.version",
    "modelOverview.baseModelIds",
    "modelOverview.owner",
    "modelOverview.status",
    "intendedUses.purpose",
    "intendedUses.outOfScope",
    "intendedUses.riskRating",
    "intendedUses.humanOversight",
    "dataSources.knowledgeBaseId",
    "dataSources.corpusRevisions",
    "promptContract.name",
    "promptContract.version",
    "promptContract.checksum",
    "guardrail.id",
    "guardrail.version",
    "evaluation.datasetRevision",
    "evaluation.metrics",
    "monitoring.metrics",
    "monitoring.thresholds",
    "risks.identified",
    "risks.mitigations",
    "approval.approvedBy",
    "approval.approvedAt",
    "approval.reviewDueDate",
    "contacts.owner",
    "contacts.escalation",
)


class ModelCardError(ValueError):
    """カードが公開の条件を満たしていない。"""


def _s3():
    kwargs: dict = {}
    if os.environ.get("AWS_ENDPOINT_URL"):
        # LocalStack では `バケット名.ホスト名` を名前解決できないため path 形式にする
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return clients.aws("s3", **kwargs)


def ensure_bucket(s3=None):
    s3 = s3 or _s3()
    try:
        s3.create_bucket(Bucket=BUCKET)
    except ClientError as error:
        if error.response["Error"]["Code"] not in (
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        ):
            raise
    return s3


def _get_path(card: dict, path: str):
    node: object = card
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def missing_fields(card: dict) -> list[str]:
    """欠けている項目を返す。**空文字・空リスト・空辞書も「欠け」とみなす。**

    キーだけ作って中身が空のカードは、無いカードより危険です
    （レビューを通った形跡だけが残る）。
    """
    missing: list[str] = []
    for path in REQUIRED_PATHS:
        value = _get_path(card, path)
        if value is None or (hasattr(value, "__len__") and len(value) == 0):
            missing.append(path)
    return sorted(missing)


def invalid_fields(card: dict) -> list[str]:
    """値域の違反を返す（状態・リスク格付け・ハッシュの長さ）。"""
    problems: list[str] = []
    status = _get_path(card, "modelOverview.status")
    if status not in STATUSES:
        problems.append(f"modelOverview.status: {status!r} は {STATUSES} 以外です")
    rating = _get_path(card, "intendedUses.riskRating")
    if rating not in RISK_RATINGS:
        problems.append(f"intendedUses.riskRating: {rating!r} は {RISK_RATINGS} 以外です")
    checksum = _get_path(card, "promptContract.checksum") or ""
    if len(checksum) != 64:
        problems.append(f"promptContract.checksum: 長さが {len(checksum)} です（SHA-256 は64）")
    return sorted(problems)


def validate(card: dict) -> dict:
    missing = missing_fields(card)
    invalid = invalid_fields(card)
    if missing or invalid:
        raise ModelCardError(f"欠落 {missing} / 値域違反 {invalid}")
    return card


def canonical(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False, sort_keys=True)


def checksum(card: dict) -> str:
    """カード自体のハッシュ。**カードにも版がある**（差し替えを検知するため）。"""
    return hashlib.sha256(canonical(card).encode("utf-8")).hexdigest()


def build(
    *,
    version: int,
    prompt: tuple[int, str],
    corpus_revisions: list[dict],
    summary: dict,
    thresholds: dict,
    approval: dict,
    measured_at: str,
    status: str = "PendingReview",
) -> dict:
    """実物から組み立てる。**手で書き写さない**のが唯一の重要な設計です。

    プロンプトの版・ハッシュ・資料の版・しきい値を人が転記すると、必ずずれます。
    ずれたカードは「説明できているつもり」を作るだけなので、実行時に読む値を
    そのまま流し込みます（だからこそ `drift` で照合できます）。
    """
    prompt_version, prompt_checksum = prompt
    return {
        "schemaVersion": SCHEMA_VERSION,
        "modelOverview": {
            "name": CARD_NAME,
            "version": version,
            "baseModelIds": [provenance.PRIMARY_MODEL, provenance.ESCALATION_MODEL],
            "owner": "情報システム部 ヘルプデスク運用",
            "status": status,
            "description": "社内規程を検索し、根拠付きで回答する社内ヘルプデスクの補助",
        },
        "intendedUses": {
            "purpose": "社員が社内規程・手続きを調べる時間を短くする",
            "outOfScope": [
                "個別の投資助言",
                "症状に対する診断や処方",
                "社外向けの公式回答をそのまま生成すること",
            ],
            "riskRating": "Medium",
            "humanOversight": "生成文を社外に出す場合は担当者が事実確認し、確認者名を記録する",
        },
        "dataSources": {
            "knowledgeBaseId": provenance.KB_ID,
            "lineageTable": lineage.TABLE,
            # 本文は入れない。**どの文書のどの版を引く仕組みなのか**だけを書く
            "corpusRevisions": corpus_revisions,
        },
        "promptContract": {
            "name": provenance.PROMPT_NAME,
            "version": prompt_version,
            "checksum": prompt_checksum,
        },
        "guardrail": {
            "id": provenance.GUARDRAIL_ID,
            "version": provenance.GUARDRAIL_VERSION,
            "deniedTopics": ["InvestmentAdvice", "MedicalDiagnosis"],
        },
        "evaluation": {
            # 指標の設計と評価ジョブはセッション18の範囲。ここに書くのは「参照」だけ
            "datasetRevision": f"governance-run/{summary['total']}件",
            "metrics": {
                "groundedRate": summary["groundedRate"],
                "zeroCitationRate": summary["zeroCitationRate"],
                "exhaustedRate": summary["exhaustedRate"],
            },
            # **測った日は「実行した日」ではなく「評価を回した日」を書く。**
            # カードの内容が毎日変わると、版が不変であることを保てない
            "measuredAt": measured_at,
        },
        "monitoring": {
            "logGroup": provenance.LOG_GROUP,
            "metrics": sorted(thresholds),
            "thresholds": thresholds,
        },
        "risks": {
            "identified": [
                "資料が古い版のまま引かれ、現行と違う回答をする",
                "引用が付かない回答をそのまま社外に転記される",
                "対象外の話題（投資・医療）に答えてしまう",
            ],
            "mitigations": [
                "引用ゼロなら基盤モデルを呼ばずに人へ回す",
                "回答1件ごとに引用の URI と版を記録し、後から根拠を再構成する",
                "ガードレールで対象外の話題を入口で止め、止めた件数も監視する",
            ],
        },
        "approval": dict(approval),
        "contacts": {
            "owner": "情報システム部 ヘルプデスク運用（内線 8100）",
            "escalation": "情報システム部 セキュリティ窓口",
        },
    }


def drift(card: dict, live: dict) -> list[str]:
    """カードと**実物**の食い違いを返す（空なら一致）。

    カードは書いた瞬間から古くなります。プロンプトの版を上げた、資料を改訂した、
    しきい値を変えた——どれもカードを黙って嘘にします。ずれを機械で見つける
    仕組みが無いモデルカードは、置いてあるだけの文書です。
    """
    problems: list[str] = []
    if _get_path(card, "promptContract.version") != live["promptVersion"]:
        problems.append("promptContract.version がプロンプトの承認版と違います")
    if _get_path(card, "promptContract.checksum") != live["promptChecksum"]:
        problems.append("promptContract.checksum が承認版のハッシュと違います")
    if _get_path(card, "guardrail.version") != live["guardrailVersion"]:
        problems.append("guardrail.version が実際に適用している版と違います")
    card_revisions = {
        (row["docId"], row["revision"])
        for row in (_get_path(card, "dataSources.corpusRevisions") or [])
    }
    if card_revisions != set(live["corpusRevisions"]):
        stale = len(set(live["corpusRevisions"]) - card_revisions)
        problems.append(f"dataSources.corpusRevisions が台帳と違います（未反映 {stale} 件）")
    return sorted(problems)


def _key(version: int) -> str:
    return f"model-cards/{CARD_NAME}/v{version}.json"


def put(s3, card: dict) -> str:
    """版として置く。**同じ版に別の内容は書けない**（プロンプトの版と同じ作法）。"""
    validate(card)
    version = card["modelOverview"]["version"]
    key = _key(version)
    try:
        existing = get(s3, version)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise
        existing = None
    if existing is not None and checksum(existing) != checksum(card):
        raise ModelCardError(f"v{version} は公開済みで内容が違います（新しい版を作ってください）")
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=canonical(card).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def get(s3, version: int) -> dict:
    obj = s3.get_object(Bucket=BUCKET, Key=_key(version))
    return json.loads(obj["Body"].read())


def live_state(ddb, s3) -> dict:
    """カードと突き合わせる「実物」を集める。"""
    prompt_version, _, prompt_checksum = provenance.registry.load_approved(
        s3, provenance.PROMPT_NAME
    )
    return {
        "promptVersion": prompt_version,
        "promptChecksum": prompt_checksum,
        "guardrailVersion": provenance.GUARDRAIL_VERSION,
        "corpusRevisions": sorted(
            (row["docId"], row["revision"]) for row in lineage.all_rows(ddb)
        ),
    }


def corpus_revisions(ddb) -> list[dict]:
    return [
        {"docId": doc_id, "revision": revision}
        for doc_id, revision in sorted(
            (row["docId"], row["revision"]) for row in lineage.all_rows(ddb)
        )
    ]


def main() -> None:
    state = provenance.bootstrap()
    s3_prompts, ddb = state["s3"], state["ddb"]
    s3 = ensure_bucket()
    live = live_state(ddb, s3_prompts)

    summary = {
        "total": 10,
        "groundedRate": 0.6667,
        "zeroCitationRate": 0.2222,
        "exhaustedRate": 0.1111,
    }
    card = build(
        version=1,
        prompt=(live["promptVersion"], live["promptChecksum"]),
        corpus_revisions=corpus_revisions(ddb),
        summary=summary,
        thresholds={"blockedRate": 0.2, "zeroCitationRate": 0.1, "exhaustedRate": 0.1},
        measured_at="2026-09-08",
        approval={
            "approvedBy": "情報システム部長 / 法務部レビュー済み",
            "approvedAt": "2026-09-08",
            "reviewDueDate": "2027-03-31",
        },
    )

    print("=== 1. 実物から組み立てる ===")
    print(f"  節: {sorted(k for k in card if k != 'schemaVersion')}")
    print(f"  欠落: {missing_fields(card)}")
    print(f"  値域違反: {invalid_fields(card)}")
    print(f"  カード自体のハッシュの長さ: {len(checksum(card))}")

    print()
    print("=== 2. 欠けていたら公開しない ===")
    broken = json.loads(canonical(card))
    broken["approval"]["approvedBy"] = ""
    broken["risks"]["mitigations"] = []
    del broken["contacts"]["escalation"]
    print(f"  欠落: {missing_fields(broken)}")
    try:
        validate(broken)
    except ModelCardError as error:
        print(f"  ModelCardError: {error}")

    print()
    print("=== 3. S3 に版として置き、読み戻す ===")
    key = put(s3, card)
    reloaded = get(s3, 1)
    print(f"  s3://{BUCKET}/{key}")
    print(f"  読み戻したカードのハッシュが一致: {checksum(reloaded) == checksum(card)}")

    print()
    print("=== 4. 実物とのずれを検知する ===")
    print(f"  いまのずれ: {drift(card, live)}")
    lineage.revise(ddb, lineage.REVISED_URI, text=lineage.REVISED_TEXT,
                   updated_at=lineage.REVISED_AT)
    after = live_state(ddb, s3_prompts)
    print(f"  資料を1件改訂したあと: {drift(card, after)}")


if __name__ == "__main__":
    main()
