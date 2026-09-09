#!/usr/bin/env python3
"""セッション6: 会話の文脈を「保存する場所」と「モデルに渡す量」を分けて持つ。

* 保存（監査・再現のため）… 全ターンを Amazon DynamoDB に置く。消さない
* 提示（精度とコストのため）… 古いターンは要約に畳み、直近だけそのまま渡す

この2つを混同すると「監査のために全部渡す」か「安くするために捨てる」の
どちらかに倒れます。置き場と提示量は別の判断です。
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session06")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import prompt_registry as registry  # noqa: E402

TABLE_NAME = "aip_c01_conversations"

# 要約は安いモデルで作る（本題の回答と同じモデルを使う必要はない）
SUMMARY_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
INTENT_MODEL_ID = "amazon.nova-micro-v1:0"

SUMMARY_SYSTEM = "あなたは会話の記録係です。事実だけを短くまとめます。"

# 意図認識で許すラベル。モデルが返した値がこの集合に無ければ既定値へ落とす
INTENT_LABELS = ("請求に関する問い合わせ", "技術的な不具合", "解約の相談")
FALLBACK_INTENT = "その他の問い合わせ"

# そのまま渡す直近ターン数（1往復 = 2ターン）
KEEP_TURNS = 2

# 会話履歴の保持期間。TTL 属性に入れて DynamoDB に自動削除させる
RETENTION_DAYS = 30


# ---------------------------------------------------------------------------
# 置き場（DynamoDB）
# ---------------------------------------------------------------------------


def ensure_table(ddb=None):
    """会話履歴テーブルを冪等に用意する。"""
    ddb = ddb or clients.aws("dynamodb")
    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "conversationId", "KeyType": "HASH"},
                {"AttributeName": "turnNo", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "conversationId", "AttributeType": "S"},
                {"AttributeName": "turnNo", "AttributeType": "N"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise
    try:
        # 保持期間をアプリのロジックではなくデータストアの機能で担保する
        ddb.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
    except ClientError:
        # すでに有効な場合は ValidationException になる。冪等に扱う
        pass
    return ddb


def append_turn(ddb, conversation_id: str, turn_no: int, role: str, text: str) -> None:
    """1ターンを追記する。

    `text` に資料（`<context>`）を混ぜないこと。履歴は「誰が何を言ったか」で、
    資料は毎回検索し直すものです。混ぜると履歴が肥大し、古い資料が復活します。
    """
    expires_at = int(time.time()) + RETENTION_DAYS * 86_400
    ddb.put_item(
        TableName=TABLE_NAME,
        Item={
            "conversationId": {"S": conversation_id},
            # 低レベル API では数値も文字列で渡す（int を渡すと ParamValidationError）
            "turnNo": {"N": str(turn_no)},
            "role": {"S": role},
            "text": {"S": text},
            "expiresAt": {"N": str(expires_at)},
        },
    )


def turns(
    ddb,
    conversation_id: str,
    *,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[dict]:
    """会話の全ターン（既定は古い順）を返す。"""
    kwargs: dict = {
        "TableName": TABLE_NAME,
        "KeyConditionExpression": "conversationId = :c",
        "ExpressionAttributeValues": {":c": {"S": conversation_id}},
        "ScanIndexForward": not newest_first,
    }
    if limit:
        kwargs["Limit"] = limit
    items = ddb.query(**kwargs)["Items"]
    return [
        {
            "turnNo": int(item["turnNo"]["N"]),
            "role": item["role"]["S"],
            "text": item["text"]["S"],
        }
        for item in items
    ]


def recent_turns(ddb, conversation_id: str, keep: int = KEEP_TURNS) -> list[dict]:
    """直近 `keep` ターンだけを、モデルに渡せる古い順で返す。"""
    rows = turns(ddb, conversation_id, limit=keep, newest_first=True)
    return sorted(rows, key=lambda row: row["turnNo"])


# ---------------------------------------------------------------------------
# 提示量の圧縮
# ---------------------------------------------------------------------------


def summarize(runtime, rows: list[dict]) -> str:
    """古いターンを1つの要約に畳む。"""
    if not rows:
        return ""
    transcript = "\n".join(f"{row['role']}: {row['text']}" for row in rows)
    response = runtime.converse(
        modelId=SUMMARY_MODEL_ID,
        system=[{"text": SUMMARY_SYSTEM}],
        messages=[
            {"role": "user", "content": [{"text": f"次の会話を要約してください。\n{transcript}"}]}
        ],
        inferenceConfig={"maxTokens": 300, "temperature": 0.0},
    )
    return registry.text_of(response)


def compact(
    runtime, ddb, conversation_id: str, keep: int = KEEP_TURNS
) -> tuple[str, list[dict]]:
    """(古いターンの要約, そのまま渡す直近ターン) を返す。

    DynamoDB の行は消しません。**畳むのは提示量だけ** で、監査のための記録は残します。
    """
    rows = turns(ddb, conversation_id)
    if len(rows) <= keep:
        return "", rows
    return summarize(runtime, rows[:-keep]), rows[-keep:]


def build_messages(
    recent: list[dict],
    question: str,
    *,
    context_text: str | None = None,
    history_summary: str | None = None,
) -> list[dict]:
    """Converse の `messages` を組み立てる。

    直近ターンはそのまま user / assistant として並べ、要約・質問・資料は
    最後の user メッセージに入れます（要約を system に足すと、可変になって
    プロンプトキャッシュが毎回外れ、利用者由来の文が指示に混ざります）。
    """
    messages = [
        {"role": row["role"], "content": [{"text": row["text"]}]} for row in recent
    ]
    messages.append(
        {
            "role": "user",
            "content": registry.render_user(
                question, context_text=context_text, history_summary=history_summary
            ),
        }
    )
    return messages


# ---------------------------------------------------------------------------
# 意図認識
# ---------------------------------------------------------------------------


def normalize_intent(label: str) -> str:
    """モデルが返したラベルを値域に押し込む。集合外なら既定ラベルへ。"""
    cleaned = label.strip()
    return cleaned if cleaned in INTENT_LABELS else FALLBACK_INTENT


def classify_intent(runtime, question: str) -> str:
    """問い合わせの意図を、決めたラベル集合の中から選ばせる。"""
    tpl = registry.local("intent-classify", 1)
    labels = "／".join(INTENT_LABELS)
    response = registry.call(
        runtime,
        tpl,
        model_id=INTENT_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"次の問い合わせを分類してください。使えるラベルは {labels} です。\n"
                            f"問い合わせ: {question}"
                        )
                    }
                ],
            }
        ],
        max_tokens=30,
    )
    return normalize_intent(registry.text_of(response))
