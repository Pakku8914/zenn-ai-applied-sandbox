#!/usr/bin/env python3
"""セッション14: 説明責任ログ（なぜその出力になったかを後から再構成する）。

    docker compose exec app python src/session14/provenance.py

残すのは本文ではなく、**後から同じ答えに到達できる手がかり**です。

    誰が            principal / department
    いつ            at
    どの指示で      promptName / promptVersion / promptChecksum
    どの資料の版を  citations（URI ＋ 台帳の版。本文は入れない）
    どのモデルで    modelId / attempts
    ガードレールは  guardrailStage / guardrailAction / guardrailPolicies
    どれだけ使って  inputTokens / outputTokens / latencyMs
    どう終わったか  outcome

セッション6の `prompt_audit.REQUIRED_FIELDS` は**変更しません**。足りない欄は
本章が上位で足します（前の章の契約を壊すと、前の章の検証が落ちます）。
セッション11のゲートウェイ監査ログとの関係も同じで、あちらが「誰が・どの版で・
何トークン・拒否も1行」を持ち、本章は**根拠（引用と版）と結末**を足します。
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session14")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402

import prompt_audit  # noqa: E402  セッション6（監査の必須項目）
import prompt_registry as registry  # noqa: E402  セッション6（版と承認）

import lineage  # noqa: E402

# 本文を持たない証跡。保持は 30 日（棚卸しと監査の周期に合わせる）
LOG_GROUP = "/sample-shoji/helpdesk/governance"
RETENTION_DAYS = 30

# **例外的に**マスク後の本文を置く場所。既定では使わない（下の注意を読むこと）
REDACTED_GROUP = "/sample-shoji/helpdesk/governance-redacted"
REDACTED_RETENTION_DAYS = 7

KB_ID = "SAMPLEKB01"
TOP_K = 3

GUARDRAIL_ID = "demo-guardrail"
GUARDRAIL_VERSION = "1"

PROMPT_NAME = "helpdesk-answer"
MAX_SENTENCES = 3
MAX_TOKENS = 300

PRIMARY_MODEL = "amazon.nova-lite-v1:0"
ESCALATION_MODEL = "amazon.nova-pro-v1:0"

# セッション6の必須項目（at / promptName / promptVersion / promptChecksum /
# modelId / conversationId / トークン / stopReason / latencyMs）に足す欄
GOVERNANCE_FIELDS = (
    "requestId",
    "principal",
    "department",
    "knowledgeBaseId",
    "citations",
    "citationCount",
    "guardrailId",
    "guardrailVersion",
    "guardrailStage",
    "guardrailAction",
    "guardrailPolicies",
    "outcome",
    "attempts",
)

# 「説明責任が果たせる」の定義。**1欄でも欠けたら再構成できない。**
ACCOUNTABILITY_FIELDS = tuple(prompt_audit.REQUIRED_FIELDS) + GOVERNANCE_FIELDS

# 結末。継続監視はこの4値を数えるだけで成り立つ
OUTCOMES = ("answered", "no_citation", "exhausted", "blocked")

# 引き受けたロールの ARN（実運用ではゲートウェイが解決したものをそのまま受け取る）
PRINCIPALS = {
    "情報システム部": "arn:aws:sts::000000000000:assumed-role/helpdesk-it/u-1043",
    "経理部": "arn:aws:sts::000000000000:assumed-role/helpdesk-finance/u-2071",
    "人事部": "arn:aws:sts::000000000000:assumed-role/helpdesk-hr/u-2210",
}

# 演習で流す10件。カテゴリのフィルタで母集団を固定してあるので結末は決定的
SCENARIOS = [
    {"id": "gov-001", "department": "人事部", "category": "人事",
     "question": "有給休暇の繰越上限は何日ですか。"},
    {"id": "gov-002", "department": "人事部", "category": "人事",
     "question": "在宅勤務は週に何日まで認められますか。"},
    {"id": "gov-003", "department": "情報システム部", "category": "IT",
     "question": "パスワードのリセットにはどの認証が必要ですか。"},
    {"id": "gov-004", "department": "経理部", "category": "経費",
     "question": "出張の宿泊費の上限はいくらですか。"},
    {"id": "gov-005", "department": "経理部", "category": "経費",
     "question": "備品購入で見積が必要になる金額はいくらですか。"},
    {"id": "gov-006", "department": "情報システム部", "category": "セキュリティ",
     "question": "情報漏えいの疑いは何分以内に報告しますか。"},
    # 該当する分類の文書が1件も無い（＝引用ゼロ。呼ばずに止める）
    {"id": "gov-007", "department": "情報システム部", "category": "法務",
     "question": "駐車場の月極料金はいくらですか。"},
    {"id": "gov-008", "department": "経理部", "category": "総務",
     "question": "社用車の予約はどこからできますか。"},
    # 資料はあるが答えが無い（上位モデルでも救えない ＝ exhausted）
    {"id": "gov-009", "department": "情報システム部", "category": "IT",
     "question": "駐車場の月極料金はいくらですか。"},
    # ガードレールが入口で止める（基盤モデルを1回も呼ばない）
    {"id": "gov-010", "department": "経理部", "category": "経費",
     "question": "余剰資金で仮想通貨に投資してもよいですか。"},
]


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    """実行ごとの識別子。ログストリームと監視のディメンションを分けるために使う。"""
    return f"run-{uuid.uuid4().hex[:8]}"


def stream_name(run_id: str) -> str:
    return f"governance/{run_id}"


def _ignore_exists(func, **kwargs) -> None:
    try:
        func(**kwargs)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise


def ensure_groups(logs=None, *, stream: str | None = None):
    """2つのロググループを作り、**保持日数を明示的に決める**。

    保持日数を設定しないロググループは「無期限」になります。無期限のログは、
    残したい証跡ではなく**消せない負債**です。仕組み自体はセッション13で
    扱いました。本章で決めるのは「どのログに何を入れ、何日残すか」です。
    """
    logs = logs or clients.aws("logs")
    for group, days in ((LOG_GROUP, RETENTION_DAYS), (REDACTED_GROUP, REDACTED_RETENTION_DAYS)):
        _ignore_exists(logs.create_log_group, logGroupName=group)
        logs.put_retention_policy(logGroupName=group, retentionInDays=days)
        if stream:
            _ignore_exists(
                logs.create_log_stream, logGroupName=group, logStreamName=stream
            )
    return logs


def retention_of(logs, group: str) -> int | None:
    res = logs.describe_log_groups(logGroupNamePrefix=group)
    for item in res.get("logGroups", []):
        if item["logGroupName"] == group:
            return item.get("retentionInDays")
    return None


# ---------------------------------------------------------------------------
# ガードレール判定の残し方
# ---------------------------------------------------------------------------


def policy_summary(assessment: dict) -> list[str]:
    """反応したポリシーの**種別だけ**を返す。

    `assessments` をそのままログに貼ってはいけません。中の `match` には
    検出した実値（メールアドレス・電話番号・ブロック語そのもの）が入るため、
    「本文は残さない」と決めたログに本文の断片が入り込みます。
    残すのは「どのポリシーが反応したか」までで十分です。
    """
    return sorted(assessment or {})


def apply_guardrail(runtime, text: str, *, source: str) -> dict:
    return runtime.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source=source,
        content=[{"text": {"text": text}}],
    )


# ---------------------------------------------------------------------------
# トークン単位のマスキング（本文を残す場合の最後の手段）
# ---------------------------------------------------------------------------

# 並び順が重要。カード番号・電話を先に潰さないと、後段の数字規則が食い違う
_MASK_RULES = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "{EMAIL}"),
    (re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"), "{CARD}"),
    (re.compile(r"\b0\d{1,4}-\d{1,4}-\d{4}\b"), "{PHONE}"),
    (re.compile(r"\d[\d,]*"), "{NUM}"),
)


def mask_tokens(text: str) -> str:
    """語（トークン）単位で置き換える。**桁数も残さない。**

    `1****0` のような伏せ字は桁数と先頭・末尾を残すため、他の情報と
    突き合わせると復元できてしまいます。`{NUM}` のように種別だけを残す形にします。

    そしてこの関数の限界を先に言います。**検出漏れは必ずあります**
    （セッション13と同じ結論）。だから第一の選択は「本文を残さない」ことで、
    マスキングは業務上どうしても本文が要るときの最後の手段です。
    """
    masked = text
    for pattern, placeholder in _MASK_RULES:
        masked = pattern.sub(placeholder, masked)
    return masked


# ---------------------------------------------------------------------------
# 1行の説明責任ログ
# ---------------------------------------------------------------------------


def _blank_entry(scenario: dict, *, request_id: str, version: int, checksum: str) -> dict:
    """**すべての結末で同じ欄がそろう形**から始める。

    欄が結末ごとに違うと、後から「拒否だけ数える」「部門別に足す」ができません。
    """
    return {
        "at": _now_iso(),
        "promptName": PROMPT_NAME,
        "promptVersion": version,
        "promptChecksum": checksum,
        "modelId": None,
        "conversationId": scenario["id"],
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadInputTokens": 0,
        "stopReason": None,
        "latencyMs": 0,
        "requestId": request_id,
        "principal": PRINCIPALS[scenario["department"]],
        "department": scenario["department"],
        "knowledgeBaseId": KB_ID,
        "citations": [],
        "citationCount": 0,
        "guardrailId": GUARDRAIL_ID,
        "guardrailVersion": GUARDRAIL_VERSION,
        "guardrailStage": None,
        "guardrailAction": None,
        "guardrailPolicies": [],
        "outcome": "no_citation",
        "attempts": [],
    }


def retrieve_citations(agent, ddb, scenario: dict) -> tuple[list[dict], str]:
    """検索結果から**引用と版**を作る。返す本文はモデルに渡すためだけに使う。

    引用の記録をモデルの自己申告に任せないのが要点です。モデルが出典を
    書き忘れても、検索層が返した URI は消えません。
    """
    res = agent.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": scenario["question"]},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": TOP_K,
                "overrideSearchType": "HYBRID",
                "filter": {"equals": {"key": "category", "value": scenario["category"]}},
            }
        },
    )
    citations: list[dict] = []
    texts: list[str] = []
    for result in res.get("retrievalResults", []):
        uri = result["location"]["s3Location"]["uri"]
        row = lineage.resolve(ddb, uri)  # 回答時点の版をここで固定する
        citations.append(
            {
                "uri": uri,
                "docId": row["docId"] if row else None,
                "revision": row["revision"] if row else None,
                "score": round(float(result["score"]), 6),
            }
        )
        texts.append(result["content"]["text"])
    return citations, "\n".join(texts)


def answer(scenario: dict, *, runtime, agent, ddb, s3, request_id: str | None = None):
    """1件を処理し、(ログ1行, 応答テキスト) を返す。"""
    request_id = request_id or scenario["id"]
    version, template, checksum = registry.load_approved(s3, PROMPT_NAME)
    entry = _blank_entry(scenario, request_id=request_id, version=version, checksum=checksum)

    # --- 1. 入口のガードレール（止めたことも記録に残す） ------------------
    verdict = apply_guardrail(runtime, scenario["question"], source="INPUT")
    entry.update(
        guardrailStage="INPUT",
        guardrailAction=verdict["action"],
        guardrailPolicies=policy_summary((verdict.get("assessments") or [{}])[0]),
    )
    if verdict["action"] == "GUARDRAIL_INTERVENED":
        entry["outcome"] = "blocked"
        return entry, None

    # --- 2. 検索（＝引用の出どころ） --------------------------------------
    citations, context_text = retrieve_citations(agent, ddb, scenario)
    entry.update(citations=citations, citationCount=len(citations))
    if not citations:
        # 根拠が無いなら呼ばない。**根拠の無い回答は説明できない回答です。**
        entry["outcome"] = "no_citation"
        return entry, None

    # --- 3. 生成（一次 → 上位。救えなければ exhausted） -------------------
    text = None
    for model_id in (PRIMARY_MODEL, ESCALATION_MODEL):
        response = registry.call(
            runtime,
            template,
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": registry.render_user(
                        scenario["question"], context_text=context_text
                    ),
                }
            ],
            params={"department": scenario["department"], "max_sentences": MAX_SENTENCES},
            max_tokens=MAX_TOKENS,
        )
        text = registry.text_of(response)
        grounded = registry.GROUNDING_MARKER in text
        usage = response["usage"]
        entry["attempts"].append(
            {
                "modelId": model_id,
                "stopReason": response["stopReason"],
                "grounded": grounded,
            }
        )
        # トークンは試行ぶんを足し上げる（切り替えた回数ぶん払っている）
        entry.update(
            modelId=model_id,
            inputTokens=entry["inputTokens"] + usage["inputTokens"],
            outputTokens=entry["outputTokens"] + usage["outputTokens"],
            cacheReadInputTokens=entry["cacheReadInputTokens"]
            + usage.get("cacheReadInputTokens", 0),
            stopReason=response["stopReason"],
            latencyMs=entry["latencyMs"] + response["metrics"]["latencyMs"],
        )
        if grounded:
            entry["outcome"] = "answered"
            break
    else:
        entry["outcome"] = "exhausted"

    # --- 4. 出口のガードレール -------------------------------------------
    out = apply_guardrail(runtime, text, source="OUTPUT")
    entry.update(
        guardrailStage="OUTPUT",
        guardrailAction=out["action"],
        guardrailPolicies=policy_summary((out.get("assessments") or [{}])[0]),
    )
    return entry, text


def write(logs, stream: str, entry: dict) -> dict:
    """1行を構造化ログとして残す。**本文はここに書かない。**"""
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


def write_redacted(logs, stream: str, *, request_id: str, text: str) -> dict:
    """マスク後の本文だけを別グループに残す（保持日数も別）。

    業務上どうしても本文の再確認が必要な場合の逃げ道です。**既定では使いません。**
    使うなら (1) マスク後だけ (2) 別のロググループ (3) 短い保持日数 の3点を必ず守ります。
    """
    record = {
        "at": _now_iso(),
        "requestId": request_id,
        "redactedText": mask_tokens(text),
    }
    logs.put_log_events(
        logGroupName=REDACTED_GROUP,
        logStreamName=stream,
        logEvents=[
            {
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(record, ensure_ascii=False),
            }
        ],
    )
    return record


def read_all(logs, stream: str, *, group: str = LOG_GROUP) -> list[dict]:
    res = logs.get_log_events(
        logGroupName=group, logStreamName=stream, startFromHead=True
    )
    return [json.loads(event["message"]) for event in res["events"]]


# ---------------------------------------------------------------------------
# 説明責任の再構成
# ---------------------------------------------------------------------------


class AccountabilityError(RuntimeError):
    """ログだけでは根拠を再構成できない（＝説明責任を果たせない）。"""


def missing_accountability_fields(entry: dict) -> list[str]:
    return [field for field in ACCOUNTABILITY_FIELDS if field not in entry]


def reconstruct(entry: dict, *, ddb) -> dict:
    """**ログ1行だけ**から、その回答の根拠を組み立て直す。

    ここが本章の判定基準です。この関数が通れば「後から説明できる」、
    落ちれば「記録が足りない」。人の記憶や画面のスクリーンショットに
    頼らず、機械が判定できる形にしておきます。
    """
    missing = missing_accountability_fields(entry)
    if missing:
        raise AccountabilityError(f"欄が足りません: {missing}")

    basis: list[dict] = []
    for citation in entry["citations"]:
        row = lineage.resolve_revision(ddb, citation["uri"], citation["revision"])
        basis.append(
            {
                "uri": citation["uri"],
                "docId": citation["docId"],
                "revision": citation["revision"],
                "score": citation["score"],
                "title": row["title"] if row else None,
                "updatedAt": row["updatedAt"] if row else None,
                "owner": row["owner"] if row else None,
                "contentHash": row["contentHash"] if row else None,
                "resolved": row is not None,
            }
        )
    return {
        "requestId": entry["requestId"],
        "at": entry["at"],
        "who": entry["principal"],
        "department": entry["department"],
        "prompt": {
            "name": entry["promptName"],
            "version": entry["promptVersion"],
            "checksum": entry["promptChecksum"],
        },
        "model": entry["modelId"],
        "attempts": entry["attempts"],
        "guardrail": {
            "id": entry["guardrailId"],
            "version": entry["guardrailVersion"],
            "stage": entry["guardrailStage"],
            "action": entry["guardrailAction"],
            "policies": entry["guardrailPolicies"],
        },
        "tokens": {
            "input": entry["inputTokens"],
            "output": entry["outputTokens"],
            "cacheRead": entry["cacheReadInputTokens"],
        },
        "outcome": entry["outcome"],
        "basis": basis,
        "unresolved": [b["uri"] for b in basis if not b["resolved"]],
    }


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def bootstrap():
    """承認済みのプロンプト版とリネージ台帳をそろえる（何度実行してもよい）。"""
    s3 = registry.ensure_bucket()
    for version in (1, 2):
        registry.publish(s3, PROMPT_NAME, version)
    registry.approve(s3, PROMPT_NAME, 2, approver="helpdesk-owner")
    state = lineage.bootstrap()
    return {"s3": s3, "ddb": state["client"], "documents": state["registered"]}


def run_all(*, run_id: str, s3, ddb, logs, runtime=None, agent=None) -> list[dict]:
    """10件を流し、1件ごとに1行の説明責任ログを残す。"""
    runtime = runtime or clients.bedrock_runtime()
    agent = agent or clients.agent_runtime()
    stream = stream_name(run_id)
    ensure_groups(logs, stream=stream)

    entries: list[dict] = []
    for scenario in SCENARIOS:
        entry, text = answer(scenario, runtime=runtime, agent=agent, ddb=ddb, s3=s3)
        write(logs, stream, entry)
        if entry["outcome"] == "answered":
            write_redacted(logs, stream, request_id=entry["requestId"], text=text)
        entries.append(entry)
    return entries


def line(entry: dict) -> str:
    return (
        f"{entry['requestId']} outcome={entry['outcome']:<12}"
        f" citations={entry['citationCount']}"
        f" attempts={len(entry['attempts'])}"
        f" guardrail={entry['guardrailStage']}/{entry['guardrailAction']}"
    )


def main() -> None:
    state = bootstrap()
    logs = clients.aws("logs")
    run_id = new_run_id()
    print(f"=== 1. 10件を流して1行ずつ残す（run={run_id}） ===")
    entries = run_all(run_id=run_id, s3=state["s3"], ddb=state["ddb"], logs=logs)
    for entry in entries:
        print(" ", line(entry))

    print()
    print("=== 2. ログだけから根拠を再構成する ===")
    target = next(e for e in read_all(logs, stream_name(run_id)) if e["outcome"] == "answered")
    report = reconstruct(target, ddb=state["ddb"])
    print(f"  requestId : {report['requestId']}")
    print(f"  誰が      : {report['who']}（{report['department']}）")
    print(f"  どの指示  : {report['prompt']['name']} v{report['prompt']['version']}"
          f"（ハッシュ {len(report['prompt']['checksum'])} 桁を照合済み）")
    print(f"  どのモデル: {report['model']}")
    print(f"  ガードレール: {report['guardrail']['stage']} / {report['guardrail']['action']}")
    print("  根拠（出力を安定させるため docId 順。版名は 更新日#ハッシュ12桁）:")
    for item in sorted(report["basis"], key=lambda b: b["docId"]):
        print(
            f"    {item['docId']} {item['title']}"
            f" 更新日={item['updatedAt']} owner={item['owner']}"
        )
    print(f"  解決できなかった引用: {len(report['unresolved'])} 件")

    print()
    print("=== 3. 欄が1つ欠けると再構成できない ===")
    broken = {k: v for k, v in target.items() if k != "promptChecksum"}
    try:
        reconstruct(broken, ddb=state["ddb"])
    except AccountabilityError as error:
        print(f"  AccountabilityError: {error}")

    print()
    print("=== 4. ログの保持日数 ===")
    print(f"  {LOG_GROUP}: {retention_of(logs, LOG_GROUP)} 日（本文なし）")
    print(f"  {REDACTED_GROUP}: {retention_of(logs, REDACTED_GROUP)} 日（マスク後のみ）")


if __name__ == "__main__":
    main()
