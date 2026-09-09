#!/usr/bin/env python3
"""セッション13の検証。

    docker compose exec app python src/session13/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * 格付けの判定が期待表と一致するか（機密以上は拒否されるか）
    * 保存後の本文に、元の PII が1文字も含まれていないか
    * 拒否した経路が、ガードレールにも基盤モデルにも1回も出ていないか
    * 検出できないもの（氏名・住所）が「残る」ことを事実として確認できるか
    * 境界（`aws:SourceVpce` と未承認モデル）で許可／拒否が変わるか
    * TTL・ライフサイクル・ログ保持日数が、設定して読み戻せるか
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session11")
sys.path.insert(0, "/workspace/src/session13")

from awskit import clients  # noqa: E402

import authz  # noqa: E402
import conversation_store as store  # noqa: E402

import anonymize  # noqa: E402
import classification as cls  # noqa: E402
import data_perimeter as perimeter  # noqa: E402
import retention  # noqa: E402
import secure_store  # noqa: E402

FAILURES: list[str] = []

NOVA_LITE = "amazon.nova-lite-v1:0"
NOVA_MICRO = "amazon.nova-micro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"

# フォームの氏名欄・住所欄から取れる値（アプリが把握している PII）
KNOWN = {"NAME": "山田太郎", "ADDRESS": "東京都千代田区1-1-1"}

FAQ_TURN = "格付け: 社内限定\n返却先は support@example.com でよいですか。"

ALL_NEEDLES = anonymize.GUARDRAIL_NEEDLES + anonymize.LOCAL_NEEDLES


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def mock_post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def mock_usage() -> dict:
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as response:
        return json.loads(response.read())


class Recorder:
    """`apply_guardrail` の呼び出しを数えるだけの薄い包み。

    「拒否した経路は外部に1回も出ていない」を証明するために使います。
    ApplyGuardrail はモックの `GET /_mock/usage` には出ないため、
    呼び出し側で数えるのが唯一の決定的な証拠になります。
    """

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []

    def apply_guardrail(self, **kwargs):
        self.calls.append(kwargs)
        return self.inner.apply_guardrail(**kwargs)


def raises_unknown_level(level: str) -> bool:
    try:
        cls.rank(level)
    except cls.UnknownLevelError:
        return True
    return False


def main() -> int:
    # 前の演習の障害注入が残っていると判定がぶれるため、冒頭で必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    recorder = Recorder(runtime)
    ddb = store.ensure_table()
    conversation_id = f"s13-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    section("1. 格付け（入れてよいかを、本文を見る前に決める）")
    check("格付け表と規程の期待表が一致する", cls.gate() == [], cls.gate())
    check(
        "先頭行の格付け表示を読める",
        cls.parse_marking(anonymize.SAMPLE_TURN) == "社内限定",
        cls.parse_marking(anonymize.SAMPLE_TURN),
    )
    check(
        "表示が無い文書は既定の機密になる（フェイルクローズ）",
        cls.parse_marking("顧客からの連絡内容です。") == "機密",
    )
    check(
        "表示が壊れていても機密へ倒れる",
        cls.parse_marking("格付け: とりあつかいちゅうい\n本文") == "機密",
    )
    check(
        "極秘は個人情報の有無に関わらず拒否",
        cls.judge("極秘", personal_data=False).action == cls.BLOCK
        and cls.judge("極秘", personal_data=True).action == cls.BLOCK,
    )
    check(
        "公開でも個人情報があれば匿名化経路へ回る",
        cls.judge("公開", personal_data=True).action == cls.ANONYMIZE_THEN_SEND,
    )
    check(
        "拒否には根拠の規程が付く（説明できない拒否を作らない）",
        cls.judge_kind("顧客マスタの抜粋").rule == "sec-001",
    )
    check("表に無い格付けは例外にする", raises_unknown_level("極秘（暫定）"))

    # ------------------------------------------------------------------
    section("2. 匿名化と、その限界")
    guardrail_only = anonymize.anonymize(runtime, anonymize.SAMPLE_TURN)
    check(
        "ガードレールが検出できるのは4種だけ",
        guardrail_only.types() == sorted(anonymize.DETECTABLE),
        guardrail_only.types(),
    )
    check(
        "4種はプレースホルダに置き換わる",
        "{EMAIL}" in guardrail_only.text and "{PHONE}" in guardrail_only.text,
    )
    check(
        "4種の原文は残らない",
        anonymize.residue(guardrail_only.text, anonymize.GUARDRAIL_NEEDLES) == [],
        anonymize.residue(guardrail_only.text, anonymize.GUARDRAIL_NEEDLES),
    )
    check(
        "自社書式（社員番号・顧客コード）はガードレールでは残る",
        anonymize.residue(guardrail_only.text, anonymize.LOCAL_NEEDLES)
        == list(anonymize.LOCAL_NEEDLES),
        anonymize.residue(guardrail_only.text, anonymize.LOCAL_NEEDLES),
    )

    scrubbed = anonymize.scrub(runtime, anonymize.SAMPLE_TURN)
    check(
        "自社ルールを足すと自社書式も残らない",
        anonymize.residue(scrubbed.text, ALL_NEEDLES) == [],
        anonymize.residue(scrubbed.text, ALL_NEEDLES),
    )
    check(
        "氏名・住所は機械的な検出では残る（これが限界）",
        anonymize.residue(scrubbed.text, anonymize.UNDETECTED_NEEDLES)
        == list(anonymize.UNDETECTED_NEEDLES),
        anonymize.residue(scrubbed.text, anonymize.UNDETECTED_NEEDLES),
    )

    with_known = anonymize.scrub(runtime, anonymize.SAMPLE_TURN, known=KNOWN)
    check(
        "アプリが知っている値なら氏名・住所も消せる",
        anonymize.residue(with_known.text, anonymize.UNDETECTED_NEEDLES) == [],
        anonymize.residue(with_known.text, anonymize.UNDETECTED_NEEDLES),
    )
    check(
        "検知の生データには原文が入っている（だからそのまま記録できない）",
        anonymize.GUARDRAIL_NEEDLES[0]
        in json.dumps(with_known.entities, ensure_ascii=False),
    )
    check(
        "記録用の要約には原文が入らない",
        anonymize.residue(
            json.dumps(with_known.summary(), ensure_ascii=False), ALL_NEEDLES
        )
        == [],
        with_known.summary(),
    )

    # ------------------------------------------------------------------
    section("3. 保存経路（保存する前に伏せる）")
    calls_before = len(recorder.calls)
    saved1 = secure_store.ingest(
        recorder,
        ddb,
        conversation_id=conversation_id,
        turn_no=1,
        role="user",
        text=anonymize.SAMPLE_TURN,
        kind="問い合わせ本文",
        known=KNOWN,
    )
    check("個人情報を含む種別は匿名化経路を通る",
          saved1.action == cls.ANONYMIZE_THEN_SEND, saved1.action)
    check("匿名化のためにガードレールを1回呼んでいる",
          len(recorder.calls) == calls_before + 1)

    saved2 = secure_store.ingest(
        recorder,
        ddb,
        conversation_id=conversation_id,
        turn_no=2,
        role="user",
        text=FAQ_TURN,
        kind="社内FAQ",
    )
    check("申告が無い経路でも検出は回す", saved2.action == cls.SEND, saved2.action)
    check(
        "申告漏れの個人情報に印が付く",
        saved2.audit["undeclared"] and saved2.audit["piiTypes"] == ["EMAIL"],
        saved2.audit,
    )
    check("申告漏れでも保存されるのは伏せたあとの本文",
          "{EMAIL}" in saved2.text and "support@example.com" not in saved2.text)

    calls_before = len(recorder.calls)
    blocked = False
    try:
        secure_store.ingest(
            recorder,
            ddb,
            conversation_id=conversation_id,
            turn_no=3,
            role="user",
            text="格付け: 機密\n顧客一覧を貼ります。",
            kind="顧客マスタの抜粋",
        )
    except secure_store.BlockedError:
        blocked = True
    check("機密の種別は保存経路の入口で止まる", blocked)
    check(
        "止めた要求はガードレールにも1回も出ていない",
        len(recorder.calls) == calls_before,
        (calls_before, len(recorder.calls)),
    )
    check("止めた要求は基盤モデルも呼んでいない", mock_usage()["calls"] == 0,
          mock_usage()["calls"])

    rows = store.turns(ddb, conversation_id)
    serialized = json.dumps(rows, ensure_ascii=False)
    check("止めたターンは行が作られない", len(rows) == 2, len(rows))
    check(
        "保存された本文に元の PII が1文字も含まれない",
        anonymize.residue(serialized, ALL_NEEDLES + anonymize.UNDETECTED_NEEDLES) == [],
        anonymize.residue(serialized, ALL_NEEDLES + anonymize.UNDETECTED_NEEDLES),
    )
    check(
        "モデルに渡す直近ターンも伏せたあとのもの",
        anonymize.residue(
            json.dumps(store.recent_turns(ddb, conversation_id), ensure_ascii=False),
            ALL_NEEDLES,
        )
        == [],
    )
    check(
        "記録（監査に渡す欄）に原文が入らない",
        anonymize.residue(
            json.dumps([saved1.audit, saved2.audit], ensure_ascii=False),
            ALL_NEEDLES + anonymize.UNDETECTED_NEEDLES,
        )
        == [],
        saved1.audit,
    )
    check(
        "セッション6のスキーマを変えていない（キーは conversationId / turnNo）",
        {row["turnNo"] for row in rows} == {1, 2}
        and all(row["role"] == "user" for row in rows),
        rows,
    )

    # ------------------------------------------------------------------
    section("4. 境界（経路と権限で、通らないと呼べない状態を作る）")
    check("境界の期待表と評価結果が一致する", perimeter.gate() == [], perimeter.gate())

    it = authz.principal_for_role("helpdesk-it")
    check(
        "境界を足す前は許可されている（セッション11の状態）",
        authz.can_invoke(it, NOVA_LITE).allowed and authz.can_invoke(it, HAIKU).allowed,
    )
    via = perimeter.can_invoke("helpdesk-it", NOVA_LITE)
    direct = perimeter.can_invoke("helpdesk-it", NOVA_LITE, vpce=None)
    check("エンドポイント経由なら通る", via.allowed, via.describe())
    check(
        "条件キーが無い経路は明示的な Deny で止まる",
        direct.reason == "explicit_deny" and direct.sid == "DenyOutsidePrivateLink",
        direct.describe(),
    )
    for model_id in (NOVA_MICRO, HAIKU):
        decision = perimeter.can_invoke("helpdesk-it", model_id)
        check(
            f"未承認モデル（{model_id}）は許可があっても拒否される",
            decision.reason == "explicit_deny"
            and decision.sid == "DenyUnapprovedModelsOnSensitivePath",
            decision.describe(),
        )
    check(
        "指定したガードレールだけ適用できる",
        perimeter.decide(
            "helpdesk-it",
            action="bedrock:ApplyGuardrail",
            resource=perimeter.GUARDRAIL_ARN,
        ).allowed
        and not perimeter.decide(
            "helpdesk-it",
            action="bedrock:ApplyGuardrail",
            resource=perimeter.OTHER_GUARDRAIL_ARN,
        ).allowed,
    )
    check(
        "指定したナレッジベースだけ検索できる",
        perimeter.decide(
            "helpdesk-it", action="bedrock:Retrieve", resource=perimeter.KB_ARN
        ).allowed
        and not perimeter.decide(
            "helpdesk-it", action="bedrock:Retrieve", resource=perimeter.OTHER_KB_ARN
        ).allowed,
    )
    check(
        "経路の境界はガードレールの適用にも効く",
        not perimeter.decide(
            "helpdesk-it",
            action="bedrock:ApplyGuardrail",
            resource=perimeter.GUARDRAIL_ARN,
            vpce=None,
        ).allowed,
    )

    # ------------------------------------------------------------------
    section("5. 保持期間（設定して読み戻す）")
    check("日数の表に矛盾が無い", retention.inconsistencies() == [],
          retention.inconsistencies())
    check(
        "会話履歴の日数はセッション6の実装から取っている",
        retention.RETENTION["conversation_ttl_days"] == store.RETENTION_DAYS,
    )

    applied = retention.apply_all(ddb=ddb)
    ttl = applied["ttl"]
    check(
        "DynamoDB の TTL が有効で、属性は expiresAt",
        ttl.get("TimeToLiveStatus") in ("ENABLED", "ENABLING")
        and ttl.get("AttributeName") == "expiresAt",
        ttl,
    )
    item = ddb.get_item(
        TableName=store.TABLE_NAME,
        Key={"conversationId": {"S": conversation_id}, "turnNo": {"N": "1"}},
    )["Item"]
    ttl_seconds = int(item["expiresAt"]["N"]) - int(time.time())
    expected_seconds = retention.RETENTION["conversation_ttl_days"] * 86_400
    check(
        "保存した行に保持期間が入っている（30日後に自動削除される）",
        abs(ttl_seconds - expected_seconds) < 120,
        (ttl_seconds, expected_seconds),
    )

    rules = {rule["ID"]: rule for rule in applied["lifecycle"]}
    check("ライフサイクルの規則が3本読み戻せる", len(rules) == 3, sorted(rules))
    raw = rules.get("expire-raw-transcripts", {})
    check(
        "raw/ は7日で削除される",
        retention.prefix_of(raw) == "raw/" and retention.expiration_days(raw) == 7,
        raw,
    )
    anon = rules.get("archive-then-expire-anonymized", {})
    transitions = anon.get("Transitions") or []
    check(
        "anonymized/ は30日でアーカイブへ移る",
        len(transitions) == 1
        and transitions[0]["Days"] == 30
        and transitions[0]["StorageClass"] == "GLACIER",
        transitions,
    )
    check(
        "anonymized/ は365日で削除される",
        retention.expiration_days(anon) == 365,
        retention.expiration_days(anon),
    )
    check(
        "中断したアップロードも片付ける規則がある",
        (rules.get("abort-stalled-uploads", {}).get("AbortIncompleteMultipartUpload")
         or {}).get("DaysAfterInitiation") == 7,
        rules.get("abort-stalled-uploads"),
    )
    check(
        "ログの保持日数が会話履歴と同じ日数で読み戻せる",
        applied["logGroup"].get("retentionInDays") == store.RETENTION_DAYS,
        applied["logGroup"].get("retentionInDays"),
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション13の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
