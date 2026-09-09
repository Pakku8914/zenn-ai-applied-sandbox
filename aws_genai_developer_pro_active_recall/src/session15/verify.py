#!/usr/bin/env python3
"""セッション15の検証。

    docker compose exec app python src/session15/verify.py

**期待値と一致しなければ非0で終了します。** 判定に使うのは決定的な性質だけです。

    * 出力契約の検査器が、欠落・値域外・契約に無い欄・偽の出典を検出できるか
    * 確信度が再計算と一致し、上限が 0.9 を超えないか（自己申告を許さない）
    * 検索を通さない経路が、必ず契約違反で人へ回されるか
    * 本章の追加欄を足しても、セッション14の説明責任ログの契約が壊れないか
    * 言い換えた組・部門だけ違う組で、根拠提示の有無が揃うか（直す前は揃わない）
    * 採点役（別モデル）の判定が機械判定と一致するか、そして
      機械判定が不合格なら採点役の判定にかかわらず不合格になるか
    * モデルカードに書いた限界の1行ごとに観測が対応づいているか
    * 方針適合の自動チェックが基盤モデルを1回も呼ばないか

採点役が返す文言そのものは合否条件にしていません（モックの採点役は採点していない
ため）。見るのは「契約を満たすか」「同じ入力なら同じ判定か」「機械判定との一致率が
正しく計算できているか」です。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

from awskit import clients  # noqa: E402

import prompt_registry as registry  # noqa: E402

import model_card  # noqa: E402
import provenance  # noqa: E402

import fairness  # noqa: E402
import judge  # noqa: E402
import policy_conformance as policy  # noqa: E402
import transparency  # noqa: E402

FAILURES: list[str] = []

EXPECTED_OUTCOMES = {
    "rai-001": "answered",
    "rai-002": "answered",
    "rai-003": "no_citation",
    "rai-004": "blocked",
    "rai-005": "escalated",
    "rai-006": "escalated",
}

EXPECTED_REASONS = {
    "rai-001": "contract-ok",
    "rai-002": "contract-ok",
    "rai-003": "no-evidence",
    "rai-004": "guardrail-input",
    "rai-005": "contract-violation",
    "rai-006": "no-answer-in-docs",
}

# 呼び出しが起きるのは answered 2件（各1回）・exhausted 1件（2回）・
# 検索を通さない経路 1件（初回 ＋ 差し戻し）だけ
EXPECTED_TRANSPARENCY_CALLS = 6
EXPECTED_FAIRNESS_CALLS = 16  # 4組 × 2通り × 2回（直す前・直した後）
EXPECTED_JUDGE_CALLS = 5  # 採点4件 ＋ 再現性の確認1件

EXPECTED_SUMMARY = {
    "total": 5,
    "attempted": 4,
    "answered": 2,
    "no_citation": 1,
    "exhausted": 1,
    "blocked": 1,
    "blockedRate": 0.2,
    "zeroCitationRate": 0.25,
    "exhaustedRate": 0.25,
    "groundedRate": 0.5,
}

MANUAL_CLAIM = "社外向けの公式回答をそのまま生成すること"

SAMPLE_ENVELOPE = {
    "traceId": "t-1",
    "answer": "提供された資料によると、あいうえおかきくけこ。",
    "citations": [
        {
            "uri": "s3://sample-shoji-docs/hr/paid-leave.md",
            "docId": "hr-001",
            "revision": "2026-04-01#0123456789ab",
            "score": 0.5,
        }
    ],
    "confidence": 0.77,
    "confidenceLabel": "high",
    "supportRatio": 1.0,
    "modelId": "amazon.nova-lite-v1:0",
    "promptVersion": 2,
    "reviewRequired": False,
    "trace": [{"step": "intake", "detail": "人事部"}],
}
SAMPLE_SOURCES = "あいうえおかきくけこ。"
SAMPLE_URIS = {"s3://sample-shoji-docs/hr/paid-leave.md"}


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


def mock_calls() -> int:
    with urllib.request.urlopen(f"{clients.mock_base_url()}/_mock/usage", timeout=10) as res:
        return json.loads(res.read())["calls"]


def codes(found: list[dict]) -> list[str]:
    return sorted({item["code"] for item in found})


def main() -> int:
    # 前の演習の障害注入と会計が残っていると呼び出し回数の突き合わせが狂う
    mock_post("/_mock/reset", {})

    state = provenance.bootstrap()
    ddb, s3_prompts = state["ddb"], state["s3"]
    runtime = clients.bedrock_runtime()

    # ------------------------------------------------------------------
    section("1. 出力契約（スキーマ1枚から検査する）")
    check("そろった封筒は契約を満たす",
          transparency.violations(SAMPLE_ENVELOPE, transparency.ANSWER_SCHEMA) == [],
          transparency.violations(SAMPLE_ENVELOPE, transparency.ANSWER_SCHEMA))
    check("空の封筒は必須欄の数だけ違反になる",
          len(transparency.violations({}, transparency.ANSWER_SCHEMA))
          == len(transparency.ANSWER_SCHEMA["required"]),
          transparency.violations({}, transparency.ANSWER_SCHEMA))
    check("整合まで見ても違反ゼロ",
          transparency.contract_violations(
              SAMPLE_ENVELOPE, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES) == [],
          transparency.contract_violations(
              SAMPLE_ENVELOPE, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES))

    broken = transparency.tamper(SAMPLE_ENVELOPE, citations_uri=judge.FAKE_URI)
    check("検索結果に無い出典は通さない",
          codes(transparency.contract_violations(
              broken, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES)) == ["unknown-citation"],
          codes(transparency.contract_violations(
              broken, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES)))

    self_reported = transparency.tamper(SAMPLE_ENVELOPE, confidence=0.95)
    check("確信度の自己申告は再計算と食い違って落ちる",
          codes(transparency.contract_violations(
              self_reported, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES))
          == ["confidence-mismatch"],
          codes(transparency.contract_violations(
              self_reported, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES)))

    extra_field = transparency.tamper(SAMPLE_ENVELOPE, extra=True)
    check("契約に無い欄を足すと落ちる",
          codes(transparency.contract_violations(
              extra_field, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES)) == ["schema"],
          codes(transparency.contract_violations(
              extra_field, allowed_uris=SAMPLE_URIS, sources=SAMPLE_SOURCES)))

    off_scale = transparency.tamper(SAMPLE_ENVELOPE, confidence=1.5)
    check("確信度が値域外なら形の検査で捕まる",
          any("上限" in detail for detail in transparency.violations(
              off_scale, transparency.ANSWER_SCHEMA)),
          transparency.violations(off_scale, transparency.ANSWER_SCHEMA))

    bad_label = json.loads(json.dumps(SAMPLE_ENVELOPE, ensure_ascii=False))
    bad_label["confidenceLabel"] = "とても高い"
    check("確信度のラベルは決めた語彙しか受け付けない",
          any("confidenceLabel" in detail for detail in transparency.violations(
              bad_label, transparency.ANSWER_SCHEMA)),
          transparency.violations(bad_label, transparency.ANSWER_SCHEMA))

    check("確信度は 0.9 を超えない（資料が正しいことは確かめていないため）",
          transparency.confidence_of(citations=[1, 2, 3], grounded=True, support=1.0)
          == (0.9, "high"),
          transparency.confidence_of(citations=[1, 2, 3], grounded=True, support=1.0))
    check("引用が無ければ確信度は 0.0",
          transparency.confidence_of(citations=[], grounded=False, support=0.0) == (0.0, "low"),
          transparency.confidence_of(citations=[], grounded=False, support=0.0))
    check("引用だけそろっていても low のまま（裏取りが無いため）",
          transparency.confidence_of(citations=[1, 2, 3], grounded=False, support=0.0)
          == (0.2, "low"),
          transparency.confidence_of(citations=[1, 2, 3], grounded=False, support=0.0))
    check("裏取りは資料に無い文を 0.0 と判定する",
          transparency.support_ratio("提供された資料によると、これは資料に無い文です。",
                                     SAMPLE_SOURCES) == 0.0)
    check("資料が空なら裏取りは 0.0",
          transparency.support_ratio(SAMPLE_ENVELOPE["answer"], "") == 0.0)

    # ------------------------------------------------------------------
    section("2. 透明性のパイプライン（6件）")
    before = mock_calls()
    results = transparency.run_all(runtime=runtime, ddb=ddb, s3=s3_prompts)
    transparency_calls = mock_calls() - before
    check("結末がすべて期待どおり",
          {key: value["outcome"] for key, value in results.items()} == EXPECTED_OUTCOMES,
          {key: value["outcome"] for key, value in results.items()})
    check("結末の理由まで期待どおり",
          {key: value["reason"] for key, value in results.items()} == EXPECTED_REASONS,
          {key: value["reason"] for key, value in results.items()})
    check("基盤モデルの呼び出し回数が期待どおり（拒否と引用ゼロは呼んでいない）",
          transparency_calls == EXPECTED_TRANSPARENCY_CALLS,
          (transparency_calls, EXPECTED_TRANSPARENCY_CALLS))
    check("封筒ができるのは契約を満たした2件だけ",
          [key for key, value in results.items() if value["envelope"]] == ["rai-001", "rai-002"],
          [key for key, value in results.items() if value["envelope"]])

    good = results["rai-001"]
    envelope = good["envelope"]
    check("引用が3件そろう", len(envelope["citations"]) == 3, len(envelope["citations"]))
    check("引用に本文は入っていない",
          all(set(citation) == {"uri", "docId", "revision", "score"}
              for citation in envelope["citations"]))
    check("裏取りが 1.0（回答の文が資料に見つかる）", envelope["supportRatio"] == 1.0,
          envelope["supportRatio"])
    check("確信度は 0.9 / high", (envelope["confidence"], envelope["confidenceLabel"]) == (0.9, "high"),
          (envelope["confidence"], envelope["confidenceLabel"]))
    check("high なら人の確認は要らない", envelope["reviewRequired"] is False)
    check("承認済みのプロンプト版が入る",
          envelope["promptVersion"] == registry.load_approved(s3_prompts, provenance.PROMPT_NAME)[0],
          envelope["promptVersion"])
    check("推論トレースが段の順に並ぶ",
          [step["step"] for step in envelope["trace"]]
          == ["intake", "guardrail-input", "retrieve", "generate"],
          [step["step"] for step in envelope["trace"]])
    check("封筒は契約を満たしている",
          transparency.contract_violations(
              envelope, allowed_uris={c["uri"] for c in good["citations"]},
              sources=good["sources"]) == [])

    view = transparency.for_user(envelope)
    check("利用者に見せる形は5つの欄だけ",
          sorted(view) == ["answer", "confidence", "reviewRequired", "sources", "steps"],
          sorted(view))
    check("利用者には数値の確信度を出さない（ラベルで見せる）",
          isinstance(view["confidence"], str) and view["confidence"] == "high",
          view["confidence"])

    fabricated = results["rai-005"]
    check("検索を通さない経路は2回試して人へ回る", len(fabricated["attempts"]) == 2,
          fabricated["attempts"])
    check("どちらの試行も同じ2種類の違反で落ちる",
          [attempt["violations"] for attempt in fabricated["attempts"]]
          == [["schema", "unsupported-answer"]] * 2,
          [attempt["violations"] for attempt in fabricated["attempts"]])
    check("契約違反が直らなければ封筒は作らない", fabricated["envelope"] is None)
    check("トレースは通った段だけを書く（検索を飛ばしたことも残る）",
          [step["step"] for step in fabricated["trace"]]
          == ["intake", "skip-retrieve", "generate", "stop"],
          [step["step"] for step in fabricated["trace"]])

    check("資料に答えが無い件は差し戻さずに人へ回す",
          results["rai-006"]["attempts"] == [], results["rai-006"]["attempts"])
    check("引用ゼロの件は基盤モデルを呼ばずに終わる",
          results["rai-003"]["entry"]["modelId"] is None
          and results["rai-003"]["entry"]["citationCount"] == 0)
    check("入口で止めた件のトレースに、通っていない段が書かれていない",
          [step["step"] for step in results["rai-004"]["trace"]]
          == ["intake", "guardrail-input", "stop"],
          [step["step"] for step in results["rai-004"]["trace"]])
    check("引用ゼロの件は検索まで進んで止まる",
          [step["step"] for step in results["rai-003"]["trace"]]
          == ["intake", "guardrail-input", "retrieve", "stop"],
          [step["step"] for step in results["rai-003"]["trace"]])

    # ------------------------------------------------------------------
    section("3. セッション14の説明責任ログに足す")
    extension = transparency.log_extension(good)
    check("追加欄は宣言したものだけ",
          sorted(extension) == sorted(transparency.LOG_EXTENSION_FIELDS), sorted(extension))
    check("追加欄はセッション14の欄名と衝突しない",
          set(transparency.LOG_EXTENSION_FIELDS)
          & set(provenance.ACCOUNTABILITY_FIELDS) == set(),
          set(transparency.LOG_EXTENSION_FIELDS) & set(provenance.ACCOUNTABILITY_FIELDS))
    merged = {**good["entry"], **extension}
    check("足したあともセッション14の必須欄がそろっている",
          provenance.missing_accountability_fields(merged) == [],
          provenance.missing_accountability_fields(merged))
    report = provenance.reconstruct(merged, ddb=ddb)
    check("足したあとも根拠を再構成できる",
          report["outcome"] == "answered" and report["unresolved"] == [],
          (report["outcome"], report["unresolved"]))
    serialized = json.dumps(
        [transparency.log_extension(value) for value in results.values()], ensure_ascii=False
    )
    check("追加欄に回答の本文が入っていない",
          registry.GROUNDING_MARKER not in serialized
          and registry.REFUSAL_MARKER not in serialized)
    check("追加欄に質問の本文が入っていない",
          all(scenario["question"] not in serialized for scenario in transparency.SCENARIOS))
    check("違反の符号は数えられる形で残る",
          transparency.log_extension(fabricated)["contractViolations"]
          == ["schema", "unsupported-answer"],
          transparency.log_extension(fabricated)["contractViolations"])

    # ------------------------------------------------------------------
    section("4. 公平性（言い換え耐性と属性の差）")
    questions = [
        variant["question"] for pair in fairness.PAIRS for variant in pair["variants"]
    ]
    check("正規化は元の質問を消さずに語を足すだけ",
          all(fairness.normalize(question).startswith(question) for question in questions))
    check("口語の質問は正規化で語が増える",
          fairness.normalize("有給って何日まで繰り越せる？") != "有給って何日まで繰り越せる？",
          fairness.normalize("有給って何日まで繰り越せる？"))
    check("すべての質問で話題から分類が決まる",
          all(fairness.category_by_topic(fairness.normalize(question)) is not None
              for question in questions),
          [(q, fairness.category_by_topic(fairness.normalize(q))) for q in questions])

    before = mock_calls()
    baseline = fairness.run_pairs(runtime=runtime, s3=s3_prompts, routing="department",
                                  normalized=False)
    fixed = fairness.run_pairs(runtime=runtime, s3=s3_prompts, routing="topic", normalized=True)
    fairness_calls = mock_calls() - before
    check("公平性の比較で呼んだ回数が期待どおり",
          fairness_calls == EXPECTED_FAIRNESS_CALLS, (fairness_calls, EXPECTED_FAIRNESS_CALLS))

    check("言い換えただけで結末が食い違う組がある",
          "leave-carryover" in baseline["unequalPairs"], baseline["unequalPairs"])
    check("食い違うのは口語で聞いた側",
          baseline["pairs"][0]["variants"][0]["grounded"] is True
          and baseline["pairs"][0]["variants"][1]["grounded"] is False,
          [variant["grounded"] for variant in baseline["pairs"][0]["variants"]])
    check("部門だけ違う組でも結末が食い違う",
          "dept-routing" in baseline["unequalPairs"], baseline["unequalPairs"])
    dept_pair = next(row for row in baseline["pairs"] if row["id"] == "dept-routing")
    check("原因は部門で母集団を絞ったこと",
          [variant["category"] for variant in dept_pair["variants"]] == ["人事", "経費"],
          [variant["category"] for variant in dept_pair["variants"]])
    check("揃っていても両方とも答えられない組がある（一致率だけを見ない）",
          baseline["equalButUngrounded"] == ["incident-report"],
          baseline["equalButUngrounded"])
    check("直す前は一致率も根拠提示率も 0.5（本文に載せた値）",
          (baseline["equalRate"], baseline["groundedRate"]) == (0.5, 0.5),
          (baseline["equalRate"], baseline["groundedRate"]))

    check("正規化と話題ルーティングで食い違いが消える", fixed["unequalPairs"] == [],
          fixed["unequalPairs"])
    check("直したあとは一致率も根拠提示率も 1.0",
          fixed["equalRate"] == 1.0 and fixed["groundedRate"] == 1.0,
          (fixed["equalRate"], fixed["groundedRate"]))
    check("直したあとは揃って答えられない組も無い", fixed["equalButUngrounded"] == [],
          fixed["equalButUngrounded"])
    check("直したあとの分類は質問の話題から決まっている",
          [variant["category"]
           for row in fixed["pairs"] if row["id"] == "dept-routing"
           for variant in row["variants"]] == ["人事", "人事"])

    # ------------------------------------------------------------------
    section("5. LLM-as-a-Judge（別モデルに採点させる）")
    cases = judge.build_cases(results)
    before = mock_calls()
    reviewed = judge.review(runtime, cases)
    again = judge.score_answer(runtime, answer=cases[0]["answer"], evidence=cases[0]["evidence"])
    judge_calls = mock_calls() - before
    check("採点で呼んだ回数が期待どおり", judge_calls == EXPECTED_JUDGE_CALLS,
          (judge_calls, EXPECTED_JUDGE_CALLS))
    check("生成役と採点役は別のモデル",
          reviewed["generatorModelId"] != reviewed["judgeModelId"],
          (reviewed["generatorModelId"], reviewed["judgeModelId"]))
    check("採点結果は契約を満たす（3つの欄がそろう）",
          all(sorted(row["judge"]) == ["judgeModelId", "labels", "reason", "verdict"]
              and row["judge"]["reason"] and isinstance(row["judge"]["labels"], list)
              for row in reviewed["rows"]),
          [sorted(row["judge"]) for row in reviewed["rows"]][:1])
    check("採点は3値のいずれか",
          all(row["judge"]["verdict"] in ("pass", "borderline", "fail")
              for row in reviewed["rows"]),
          [row["judge"]["verdict"] for row in reviewed["rows"]])
    check("同じ入力なら同じ採点になる（温度0）", again == reviewed["rows"][0]["judge"],
          (again, reviewed["rows"][0]["judge"]))

    by_id = {row["id"]: row for row in reviewed["rows"]}
    check("機械判定は引用付きの回答だけを合格にする",
          {key: row["mechanical"]["verdict"] for key, row in by_id.items()}
          == {"j-01": "pass", "j-02": "fail", "j-03": "fail", "j-04": "fail"},
          {key: row["mechanical"]["verdict"] for key, row in by_id.items()})
    check("差し替えた出典は名前で分かる",
          by_id["j-04"]["mechanical"]["unknownCitations"] == [judge.FAKE_URI],
          by_id["j-04"]["mechanical"]["unknownCitations"])
    check("機械判定が不合格なら採点役の判定にかかわらず不合格",
          all(by_id[key]["final"] == "fail" for key in ("j-02", "j-03", "j-04")),
          {key: by_id[key]["final"] for key in ("j-02", "j-03", "j-04")})
    check("機械判定が拒否権を使った件が記録される",
          reviewed["vetoed"] == ["j-02", "j-03", "j-04"], reviewed["vetoed"])
    check("一致率は一致件数と母数から計算されている",
          reviewed["agreementRate"]
          == round(sum(1 for row in reviewed["rows"] if row["agreed"]) / reviewed["total"], 4)
          and 0.0 <= reviewed["agreementRate"] <= 1.0,
          reviewed["agreementRate"])
    print(f"  参考 一致率: {reviewed['agreementRate']}"
          f"（モックの採点役は採点していないため、値そのものは合否条件にしない）")

    raised = False
    try:
        judge.assert_distinct_models(judge.GENERATOR_MODEL, judge.GENERATOR_MODEL)
    except judge.SelfGradingError:
        raised = True
    check("同じモデルに自分を採点させようとすると止まる", raised)

    # ------------------------------------------------------------------
    section("6. 方針適合（カードの限界 ↔ 実際の挙動）")
    entries = [value["entry"] for value in results.values() if value["entry"] is not None]
    check("説明責任ログは封筒を作らなかった件も含めて残る", len(entries) == 5, len(entries))
    before = mock_calls()
    card, live, summary = policy.build_card(entries=entries, ddb=ddb, s3_prompts=s3_prompts)
    check("観測した結末の集計が期待どおり",
          all(summary[key] == value for key, value in EXPECTED_SUMMARY.items()),
          {key: summary[key] for key in EXPECTED_SUMMARY})
    check("カードに欠落と値域違反が無い",
          model_card.missing_fields(card) == [] and model_card.invalid_fields(card) == [],
          (model_card.missing_fields(card), model_card.invalid_fields(card)))
    check("カードと実物がずれていない", model_card.drift(card, live) == [],
          model_card.drift(card, live))

    rows = policy.check(card, runtime=runtime, results=results, live=live)
    policy_calls = mock_calls() - before
    check("方針適合の自動チェックは基盤モデルを1回も呼ばない", policy_calls == 0, policy_calls)
    check("カードの限界の全行に観測が対応づいている",
          policy.missing_claims(card, rows) == [], policy.missing_claims(card, rows))
    check("観測できるはずの主張はすべて期待どおり", policy.failures(rows) == [],
          policy.failures(rows))
    check("機械で確かめられない主張は1件で、人手の運用に紐づけてある",
          policy.unverifiable(rows) == [MANUAL_CLAIM], policy.unverifiable(rows))
    check("投資と医療の質問は入口で止まる",
          all(item["action"] == policy.BLOCKED and item["policies"] == ["topicPolicy"]
              for row in rows if row["how"] == "guardrail" for item in row["observed"]),
          [row["observed"] for row in rows if row["how"] == "guardrail"])

    extended = json.loads(model_card.canonical(card))
    extended["intendedUses"]["outOfScope"].append("英語での回答")
    check("限界を1行足して観測を書き忘れると検出される",
          policy.missing_claims(extended, rows) == ["英語での回答"],
          policy.missing_claims(extended, rows))

    s3_cards = model_card.ensure_bucket()
    key = model_card.put(s3_cards, card)
    check("観測を反映したカードを新しい版として置ける",
          key.endswith(f"v{policy.CARD_VERSION}.json")
          and model_card.checksum(model_card.get(s3_cards, policy.CARD_VERSION))
          == model_card.checksum(card), key)
    check("カードに本文は入っていない",
          registry.GROUNDING_MARKER not in json.dumps(card, ensure_ascii=False)
          and "繰り越せます" not in json.dumps(card, ensure_ascii=False))

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション15の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
