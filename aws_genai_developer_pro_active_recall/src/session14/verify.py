#!/usr/bin/env python3
"""セッション14の検証。

    docker compose exec app python src/session14/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * ログ1行だけから、1件の回答の根拠を再構成できるか（欄がそろっているか）
    * 引用の URI が、リネージ台帳の正しい文書・正しい版に解決できるか
    * 文書を改訂しても、**そのとき根拠にした版**を引けるか
    * モデルカードの欠落検出が正しいか（空文字・空配列も欠落とみなすか）
    * しきい値を超えたときだけ通知が発火するか（超過が無ければ0通）
    * ログと通知に本文（質問・回答・プロンプト）が入っていないか

トークン数の絶対値は system の長さで変わるため合否条件にしていません
（「0より大きい」「試行ぶん足し上げられている」のような関係だけを見ます）。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session14")

from awskit import clients  # noqa: E402

import prompt_audit  # noqa: E402
import prompt_registry as registry  # noqa: E402

import continuous_monitoring as monitoring  # noqa: E402
import lineage  # noqa: E402
import model_card  # noqa: E402
import provenance  # noqa: E402

FAILURES: list[str] = []

EXPECTED_DOCUMENTS = 12

EXPECTED_OUTCOMES = {
    "gov-001": "answered",
    "gov-002": "answered",
    "gov-003": "answered",
    "gov-004": "answered",
    "gov-005": "answered",
    "gov-006": "answered",
    "gov-007": "no_citation",
    "gov-008": "no_citation",
    "gov-009": "exhausted",
    "gov-010": "blocked",
}

# 呼び出しが起きるのは answered 6件（各1回）と exhausted 1件（2回）だけ
EXPECTED_CALLS = 8

EXPECTED_SUMMARY = {
    "total": 10,
    "attempted": 9,
    "answered": 6,
    "no_citation": 2,
    "exhausted": 1,
    "blocked": 1,
    "blockedRate": 0.1,
    "zeroCitationRate": 0.2222,
    "exhaustedRate": 0.1111,
    "groundedRate": 0.6667,
}

HR_URI = lineage.REVISED_URI


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def mock_usage() -> dict:
    with urllib.request.urlopen(f"{clients.mock_base_url()}/_mock/usage", timeout=10) as res:
        return json.loads(res.read())


def main() -> int:
    # 前の演習の障害注入と会計が残っていると呼び出し回数の突き合わせが狂う
    mock_post("/_mock/reset", {})

    state = provenance.bootstrap()
    s3_prompts, ddb = state["s3"], state["ddb"]
    logs = clients.aws("logs")
    run_id = provenance.new_run_id()
    stream = provenance.stream_name(run_id)

    # ------------------------------------------------------------------
    section("1. リネージ台帳（出典と版の原簿）")
    check("取り込み元の文書がすべて登録される",
          state["documents"] == EXPECTED_DOCUMENTS and lineage.count(ddb) == EXPECTED_DOCUMENTS,
          (state["documents"], lineage.count(ddb)))
    row = lineage.resolve(ddb, HR_URI)
    check("引用の URI から文書 ID が引ける", row is not None and row["docId"] == "hr-001",
          row and row["docId"])
    check("版は更新日とハッシュでできている",
          row["revision"] == lineage.revision_of(row["updatedAt"], row["contentHash"]),
          row["revision"])
    check("所管部門がメタデータとして付いている", row["owner"] == "人事部", row["owner"])
    check("台帳に本文は入っていない",
          set(row) == set(lineage.FIELDS) and "text" not in row and "content" not in row,
          sorted(row))
    table_dump = json.dumps(lineage.all_rows(ddb), ensure_ascii=False)
    check("台帳の全文に文書本文の断片が現れない",
          "繰り越せます" not in table_dump and "SMS認証" not in table_dump)
    check("台帳に無い版は解決できない（Noneが返る）",
          lineage.resolve_revision(ddb, HR_URI, "2020-01-01#deadbeefdead") is None)

    # ------------------------------------------------------------------
    section("2. 説明責任ログ（1件ごとに1行）")
    entries = provenance.run_all(run_id=run_id, s3=s3_prompts, ddb=ddb, logs=logs)
    stored = provenance.read_all(logs, stream)
    check("流した件数と残った行数が一致する", len(stored) == len(provenance.SCENARIOS),
          (len(stored), len(provenance.SCENARIOS)))
    check("結末がすべて期待どおり",
          {e["requestId"]: e["outcome"] for e in stored} == EXPECTED_OUTCOMES,
          {e["requestId"]: e["outcome"] for e in stored})

    required = provenance.ACCOUNTABILITY_FIELDS
    missing = sorted({f for e in stored for f in required if f not in e})
    check("すべての行に説明責任の欄がそろう（セッション6の契約 ＋ 本章の追加欄）",
          missing == [], missing)
    check("セッション6の必須項目を1つも落としていない",
          set(prompt_audit.REQUIRED_FIELDS) <= set(required))

    serialized = json.dumps(stored, ensure_ascii=False)
    check("質問の本文がログに残っていない",
          all(s["question"] not in serialized for s in provenance.SCENARIOS))
    check("回答の本文がログに残っていない",
          registry.GROUNDING_MARKER not in serialized
          and registry.REFUSAL_MARKER not in serialized)
    check("プロンプト本文がログに残っていない", "あなたはサンプル商事" not in serialized)
    check("引用に本文を持たせていない",
          all(set(c) == {"uri", "docId", "revision", "score"}
              for e in stored for c in e["citations"]),
          [sorted(c) for e in stored for c in e["citations"]][:1])

    approved_version, _, approved_checksum = registry.load_approved(
        s3_prompts, provenance.PROMPT_NAME
    )
    check("全行に承認済みの版とハッシュが入る",
          all(e["promptVersion"] == approved_version
              and e["promptChecksum"] == approved_checksum for e in stored))

    by_id = {e["requestId"]: e for e in stored}
    answered = [e for e in stored if e["outcome"] == "answered"]
    check("回答できた行には引用が3件付く",
          all(e["citationCount"] == 3 for e in answered),
          [e["citationCount"] for e in answered])
    check("回答できた行にはモデル ID とトークンが入る",
          all(e["modelId"] == provenance.PRIMARY_MODEL and e["inputTokens"] > 0
              and e["outputTokens"] > 0 and e["stopReason"] for e in answered),
          [(e["requestId"], e["modelId"]) for e in answered])

    blocked = by_id["gov-010"]
    check("ガードレールで止めた行は入口で終わっている",
          blocked["guardrailStage"] == "INPUT"
          and blocked["guardrailAction"] == "GUARDRAIL_INTERVENED",
          (blocked["guardrailStage"], blocked["guardrailAction"]))
    check("止めた行に反応したポリシーの種別が残る",
          blocked["guardrailPolicies"] == ["topicPolicy"], blocked["guardrailPolicies"])
    check("止めた行はモデル ID もトークンも空",
          blocked["modelId"] is None and blocked["inputTokens"] == 0
          and blocked["citationCount"] == 0)

    zero = by_id["gov-007"]
    check("引用ゼロの行は基盤モデルを呼ばずに終わる",
          zero["citationCount"] == 0 and zero["modelId"] is None and zero["attempts"] == [],
          (zero["citationCount"], zero["modelId"]))

    exhausted = by_id["gov-009"]
    check("救えなかった行には2回の試行が残る",
          [a["modelId"] for a in exhausted["attempts"]]
          == [provenance.PRIMARY_MODEL, provenance.ESCALATION_MODEL],
          exhausted["attempts"])
    check("どちらの試行も根拠に届いていない",
          all(a["grounded"] is False for a in exhausted["attempts"]))
    check("トークンは試行ぶん足し上げられている",
          exhausted["inputTokens"] > 0 and exhausted["outputTokens"] > 0
          and exhausted["latencyMs"] > 0)

    usage = mock_usage()
    check("基盤モデルの呼び出し回数が期待どおり（拒否と引用ゼロは呼んでいない）",
          usage["calls"] == EXPECTED_CALLS, (usage["calls"], EXPECTED_CALLS))

    # ------------------------------------------------------------------
    section("3. ログだけから根拠を再構成する")
    report = provenance.reconstruct(by_id["gov-001"], ddb=ddb)
    check("誰が・どの部門かが復元できる",
          report["who"] == provenance.PRINCIPALS["人事部"] and report["department"] == "人事部",
          (report["who"], report["department"]))
    check("どの指示の版で答えたかが復元できる",
          report["prompt"]["version"] == approved_version
          and report["prompt"]["checksum"] == approved_checksum)
    check("根拠の文書が台帳に解決できる", report["unresolved"] == [], report["unresolved"])
    check("根拠が人事カテゴリの3文書に解決される",
          {b["docId"] for b in report["basis"]} == {"hr-001", "hr-002", "hr-003"},
          sorted(b["docId"] for b in report["basis"]))
    check("根拠には題名・更新日・所管が付く",
          all(b["title"] and b["updatedAt"] and b["owner"] for b in report["basis"]))
    check("再構成の結果にも本文は現れない",
          registry.GROUNDING_MARKER not in json.dumps(report, ensure_ascii=False))

    it_report = provenance.reconstruct(by_id["gov-003"], ddb=ddb)
    check("別部門の行も同じ手順で再構成できる",
          {b["docId"] for b in it_report["basis"]} == {"hd-001", "hd-002", "hd-003"},
          sorted(b["docId"] for b in it_report["basis"]))

    broken = {k: v for k, v in by_id["gov-001"].items() if k != "promptChecksum"}
    raised = False
    try:
        provenance.reconstruct(broken, ddb=ddb)
    except provenance.AccountabilityError:
        raised = True
    check("欄が1つ欠けたら再構成は失敗する（説明責任を果たせない）", raised)
    check("欠落は名前で分かる",
          provenance.missing_accountability_fields(broken) == ["promptChecksum"],
          provenance.missing_accountability_fields(broken))

    tampered = json.loads(json.dumps(by_id["gov-001"], ensure_ascii=False))
    tampered["citations"][0]["revision"] = "2020-01-01#deadbeefdead"
    check("台帳から版が消えていれば、解決できない引用として報告される",
          len(provenance.reconstruct(tampered, ddb=ddb)["unresolved"]) == 1)

    # ------------------------------------------------------------------
    section("4. モデルカード（この仕組みの説明書）")
    s3_cards = model_card.ensure_bucket()
    live = model_card.live_state(ddb, s3_prompts)
    summary = monitoring.aggregate(entries)
    card = model_card.build(
        version=1,
        prompt=(live["promptVersion"], live["promptChecksum"]),
        corpus_revisions=model_card.corpus_revisions(ddb),
        summary=summary,
        thresholds=monitoring.THRESHOLDS,
        # 日付を固定する。**カードの内容が日替わりで変わると版を不変に保てない**
        measured_at="2026-09-08",
        approval={
            "approvedBy": "情報システム部長 / 法務部レビュー済み",
            "approvedAt": "2026-09-08",
            "reviewDueDate": "2027-03-31",
        },
    )
    check("実物から組み立てたカードに欠落が無い", model_card.missing_fields(card) == [],
          model_card.missing_fields(card))
    check("値域違反が無い", model_card.invalid_fields(card) == [],
          model_card.invalid_fields(card))
    check("カードのプロンプト版が承認版と一致する",
          card["promptContract"]["version"] == approved_version
          and card["promptContract"]["checksum"] == approved_checksum)
    check("カードに本文は入っていない",
          registry.GROUNDING_MARKER not in json.dumps(card, ensure_ascii=False)
          and "繰り越せます" not in json.dumps(card, ensure_ascii=False))

    incomplete = json.loads(model_card.canonical(card))
    incomplete["approval"]["approvedBy"] = ""
    incomplete["risks"]["mitigations"] = []
    del incomplete["contacts"]["escalation"]
    check("空文字・空配列・キー欠落をすべて欠落として検出する",
          model_card.missing_fields(incomplete)
          == ["approval.approvedBy", "contacts.escalation", "risks.mitigations"],
          model_card.missing_fields(incomplete))
    rejected = False
    try:
        model_card.put(s3_cards, incomplete)
    except model_card.ModelCardError:
        rejected = True
    check("欠落のあるカードは公開できない", rejected)

    off_scale = json.loads(model_card.canonical(card))
    off_scale["modelOverview"]["status"] = "公開中"
    off_scale["intendedUses"]["riskRating"] = "やや高い"
    check("状態とリスク格付けは決めた語彙しか受け付けない",
          len(model_card.invalid_fields(off_scale)) == 2,
          model_card.invalid_fields(off_scale))

    key = model_card.put(s3_cards, card)
    reloaded = model_card.get(s3_cards, 1)
    check("S3 に版として置いて読み戻せる",
          key.endswith("v1.json")
          and model_card.checksum(reloaded) == model_card.checksum(card))
    check("いまはカードと実物がずれていない", model_card.drift(card, live) == [],
          model_card.drift(card, live))

    stale_card = json.loads(model_card.canonical(card))
    stale_card["promptContract"]["checksum"] = "0" * 64
    check("ハッシュが違えばずれとして検出される",
          any("checksum" in problem for problem in model_card.drift(stale_card, live)),
          model_card.drift(stale_card, live))

    # ------------------------------------------------------------------
    section("5. 文書の改訂と、時点の再現")
    pinned = by_id["gov-001"]["citations"]
    pinned_revision = next(c["revision"] for c in pinned if c["docId"] == "hr-001")
    revised = lineage.revise(
        ddb, HR_URI, text=lineage.REVISED_TEXT, updated_at=lineage.REVISED_AT
    )
    check("改訂すると版が2つになる", len(lineage.revisions(ddb, HR_URI)) == 2,
          lineage.revisions(ddb, HR_URI))
    check("最新版は新しい方に切り替わる",
          lineage.resolve(ddb, HR_URI)["revision"] == revised["revision"]
          and revised["revision"] != pinned_revision,
          (revised["revision"], pinned_revision))
    after = provenance.reconstruct(by_id["gov-001"], ddb=ddb)
    hr_basis = next(b for b in after["basis"] if b["docId"] == "hr-001")
    check("過去の回答は当時の版に解決され続ける",
          hr_basis["revision"] == pinned_revision and hr_basis["resolved"],
          hr_basis["revision"])
    check("当時の版の更新日が返る（最新の更新日ではない）",
          hr_basis["updatedAt"] != lineage.REVISED_AT, hr_basis["updatedAt"])
    check("資料が改訂されるとモデルカードはずれる",
          any("corpusRevisions" in problem
              for problem in model_card.drift(card, model_card.live_state(ddb, s3_prompts))),
          model_card.drift(card, model_card.live_state(ddb, s3_prompts)))

    # ------------------------------------------------------------------
    section("6. 継続監視（数える → メトリクス → 通知）")
    check("集計値が期待どおり",
          all(summary[key] == value for key, value in EXPECTED_SUMMARY.items()),
          {k: summary[k] for k in EXPECTED_SUMMARY})
    check("拒否率の分母は全件、引用ゼロ率の分母は入口を通った件",
          summary["blockedRate"] == round(summary["blocked"] / summary["total"], 4)
          and summary["zeroCitationRate"]
          == round(summary["no_citation"] / summary["attempted"], 4))

    found = monitoring.breaches(summary)
    check("超過するのは引用ゼロ率と exhausted 率の2つ",
          [b["metric"] for b in found] == ["exhaustedRate", "zeroCitationRate"],
          [b["metric"] for b in found])
    check("しきい値内の拒否率は通知対象にならない",
          all(b["metric"] != "blockedRate" for b in found))
    check("超過ごとに起動する是正処理が決まっている",
          {b["action"] for b in found} == {"reindex-corpus", "escalate-to-human"},
          [b["action"] for b in found])

    cw = clients.aws("cloudwatch")
    published = monitoring.publish_metrics(cw, summary, run_id=run_id)
    check("メトリクスは3本の割合と母数の合計4本", sorted(published) == sorted(
        [monitoring.COUNT_METRIC, *monitoring.METRIC_OF.values()]), sorted(published))
    listed = monitoring.listed_metrics(cw, run_id=run_id)
    check("書いたメトリクスが読み戻せる", listed == sorted(published), listed)
    total_points = monitoring.read_count_metric(cw, run_id=run_id)
    check("母数のメトリクスの値が集計と一致する",
          total_points == float(summary["total"]), total_points)

    channels = monitoring.ensure_channels()
    monitoring.drain(channels["inboxUrl"])
    monitoring.drain(channels["actionUrl"])
    sent = monitoring.notify(found, summary, channels=channels, run_id=run_id)
    check("超過ぶんだけ通知する", sent == len(found), sent)

    inbox = monitoring.receive(channels["inboxUrl"], expected=sent)
    check("人向けの通知（SNS）が届く", len(inbox) == sent, len(inbox))
    payloads = [json.loads(message["Body"]) for message in inbox]
    check("通知に指標・値・しきい値・母数が入る",
          all({"metric", "value", "threshold", "window", "action"} <= set(p)
              for p in payloads), [sorted(p) for p in payloads][:1])
    check("通知に本文は入っていない",
          all(s["question"] not in json.dumps(payloads, ensure_ascii=False)
              for s in provenance.SCENARIOS))

    actions = monitoring.receive(channels["actionUrl"], expected=sent)
    check("機械向けの通知（EventBridge）が届く", len(actions) == sent, len(actions))
    details = [json.loads(message["Body"]) for message in actions]
    check("イベントの種別でルールが絞られている",
          all(d.get("detail-type") == monitoring.DETAIL_TYPE for d in details),
          [d.get("detail-type") for d in details])

    monitoring.drain(channels["inboxUrl"])
    monitoring.drain(channels["actionUrl"])
    quiet = monitoring.notify([], summary, channels=channels, run_id=run_id)
    check("超過が無ければ1通も送らない", quiet == 0, quiet)
    check("超過が無いときはキューに何も届かない",
          monitoring.receive(channels["inboxUrl"], expected=1, timeout=4.0) == [])

    # ------------------------------------------------------------------
    section("7. 本文の扱い（マスキングと保持日数）")
    check("メールアドレス・電話・カード番号・数字がすべて置き換わる",
          not any(ch.isdigit() for ch in provenance.mask_tokens(
              "連絡は taro@example.com か 03-1234-5678、カードは 4111-1111-1111-1111 です。")),
          provenance.mask_tokens(
              "連絡は taro@example.com か 03-1234-5678、カードは 4111-1111-1111-1111 です。"))
    masked = provenance.mask_tokens("内線8100 に連絡してください。")
    check("桁数も残さない（種別だけを残す）",
          "{NUM}" in masked and "8100" not in masked and "8***" not in masked, masked)
    check("ガードレールの assessments から検出した実値を取り出さない",
          provenance.policy_summary(
              {"sensitiveInformationPolicy":
               {"piiEntities": [{"match": "taro@example.com", "type": "EMAIL"}]}})
          == ["sensitiveInformationPolicy"])

    redacted = provenance.read_all(logs, stream, group=provenance.REDACTED_GROUP)
    check("マスク後の本文は別のロググループにだけ置かれる",
          len(redacted) == EXPECTED_SUMMARY["answered"], len(redacted))
    check("マスク後の本文に数字が残っていない",
          all(not any(ch.isdigit() for ch in r["redactedText"]) for r in redacted),
          [r["redactedText"] for r in redacted][:1])
    check("証跡のロググループは30日で消える",
          provenance.retention_of(logs, provenance.LOG_GROUP) == provenance.RETENTION_DAYS,
          provenance.retention_of(logs, provenance.LOG_GROUP))
    check("マスク後の本文のグループはもっと短い",
          provenance.retention_of(logs, provenance.REDACTED_GROUP)
          == provenance.REDACTED_RETENTION_DAYS,
          provenance.retention_of(logs, provenance.REDACTED_GROUP))

    # ------------------------------------------------------------------
    # 後片付け。台帳を取り込み元の状態に戻す（次の実行を同じ状態から始めるため）
    lineage.bootstrap(ddb)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション14の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
