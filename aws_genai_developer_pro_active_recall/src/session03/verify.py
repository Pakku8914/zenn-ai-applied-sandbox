#!/usr/bin/env python3
"""セッション3の検証。

1. モデル固有の3形式が「形だけ違って中身は同じ」ことを確認する
2. Converse API がその差を吸収することを確認する
3. 検証関数が壊れた入力を規則どおりに遮断・修復することを確認する
4. 遮断したデータが隔離ストア（S3）と再処理キュー（SQS）に流れることを確認する

**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session03/verify.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session03")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import ingest_pipeline  # noqa: E402
import input_guard  # noqa: E402
import native_formats  # noqa: E402

FAILURES: list[str] = []

# QUESTION（system プロンプトなし）を投げたときの決定的な計測値。
# 入力57 tok は「セッション1の 90 tok − system の 33 tok」と一致する
EXPECTED_INPUT_TOKENS = 57
EXPECTED_OUTPUT_TOKENS = 66
EXPECTED_LATENCY_MS = 20 + EXPECTED_OUTPUT_TOKENS  # モックのレイテンシ規則

GROUNDING_MARKER = "提供された資料によると、"
ANSWER_FRAGMENT = "繰越上限は20日です。"

# ネイティブ形式ごとの停止理由。同じ「言い切って終わった」を別の名前で返す
EXPECTED_STOP = {"anthropic": "end_turn", "nova": "end_turn", "meta": "stop"}

# 取り込みバッチ（正常12件＋壊れた6件）の期待値
EXPECTED_SUMMARY = {
    "total": 18,
    "accepted": 13,
    "repaired": 1,
    "quarantined": 5,
    "quarantineRate": 0.278,
    "alert": True,
}
EXPECTED_BY_RULE = {
    "mojibake": 1,
    "empty": 1,
    "too_long": 1,
    "pii": 1,
    "duplicate": 1,
}
EXPECTED_QUARANTINED_IDS = {"bad-001", "bad-002", "bad-003", "bad-005", "bad-006"}

# 隔離レコードに絶対に現れてはいけない文字列（機密を別ストアへ複製していないことの確認）
PII_LITERALS = ("tanaka@example.com", "090-1234-5678", "123456789012")

RUN_ID = "verify03"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def drain_queue(sqs, queue_url: str, max_rounds: int = 12) -> list[dict]:
    """キューを空になるまで受信して削除し、本文を返す。

    前回の実行分が残っていると件数の検証がぶれるため、
    パイプラインの実行前後にこれで空にします。
    """
    drained: list[dict] = []
    empty_rounds = 0
    for _ in range(max_rounds):
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        messages = response.get("Messages", [])
        if not messages:
            empty_rounds += 1
            if empty_rounds >= 2:
                break
            continue
        empty_rounds = 0
        for message in messages:
            drained.append(json.loads(message["Body"]))
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
    return drained


def main() -> int:
    # 前セッションの障害注入設定が残っていると落ちるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()

    # ------------------------------------------------------------------
    section("1. モデル固有のリクエスト形式")
    check(
        "使うモデル ID は3件すべてカタログにある",
        all(m in catalog.MODELS for m in native_formats.MODELS.values()),
        native_formats.MODELS,
    )
    anthropic_body = native_formats.build_body("anthropic", "x")
    nova_body = native_formats.build_body("nova", "x")
    meta_body = native_formats.build_body("meta", "x")
    check(
        "Anthropic 形式は max_tokens と messages を持つ",
        anthropic_body["max_tokens"] == native_formats.MAX_TOKENS
        and "messages" in anthropic_body,
        sorted(anthropic_body),
    )
    check(
        "Nova 形式は上限を inferenceConfig.maxTokens に入れる",
        nova_body["inferenceConfig"]["maxTokens"] == native_formats.MAX_TOKENS
        and "max_tokens" not in nova_body,
        sorted(nova_body),
    )
    check(
        "Meta 形式は messages を持たず prompt と max_gen_len を使う",
        "messages" not in meta_body
        and meta_body["max_gen_len"] == native_formats.MAX_TOKENS
        and isinstance(meta_body["prompt"], str),
        sorted(meta_body),
    )

    # ------------------------------------------------------------------
    section("2. 同じ質問を3形式で投げる（InvokeModel）")
    natives: dict[str, dict] = {}
    payloads: dict[str, dict] = {}
    for family in ("anthropic", "nova", "meta"):
        parsed, payload = native_formats.invoke_native(runtime, family)
        natives[family] = parsed
        payloads[family] = payload

    check(
        "Anthropic のテキストは content[0].text にある",
        "content" in payloads["anthropic"]
        and "input_tokens" in payloads["anthropic"]["usage"],
        sorted(payloads["anthropic"]),
    )
    check(
        "Nova のテキストは output.message.content[0].text にある",
        "output" in payloads["nova"] and "inputTokens" in payloads["nova"]["usage"],
        sorted(payloads["nova"]),
    )
    check(
        "Meta のテキストは generation にあり usage が存在しない",
        "generation" in payloads["meta"]
        and "usage" not in payloads["meta"]
        and "prompt_token_count" in payloads["meta"],
        sorted(payloads["meta"]),
    )
    check(
        "3形式のトップレベルのキーは互いに異なる",
        "content" not in payloads["nova"]
        and "output" not in payloads["anthropic"]
        and "generation" not in payloads["nova"],
        {f: sorted(p) for f, p in payloads.items()},
    )
    for family, expected in EXPECTED_STOP.items():
        check(
            f"{family} の停止理由は {expected}",
            natives[family]["stopReason"] == expected,
            natives[family]["stopReason"],
        )
    check(
        "3形式の回答テキストは完全に一致する",
        len({r["text"] for r in natives.values()}) == 1,
        [r["text"][:20] for r in natives.values()],
    )
    check(
        "回答は資料を根拠にしている",
        all(
            GROUNDING_MARKER in r["text"] and ANSWER_FRAGMENT in r["text"]
            for r in natives.values()
        ),
        natives["nova"]["text"][:40],
    )
    for family, r in natives.items():
        actual = (r["inputTokens"], r["outputTokens"], r["latencyMs"])
        check(
            f"{family} の計測値が決定的（入力/出力/ms）",
            actual
            == (EXPECTED_INPUT_TOKENS, EXPECTED_OUTPUT_TOKENS, EXPECTED_LATENCY_MS),
            actual,
        )

    # ------------------------------------------------------------------
    section("3. Converse API が形の差を吸収する")
    converses = {
        family: native_formats.invoke_converse(runtime, model_id)
        for family, model_id in native_formats.MODELS.items()
    }
    check(
        "3モデルすべてが同じ取り出し方で読める",
        all(GROUNDING_MARKER in r["text"] for r in converses.values()),
        [r["text"][:20] for r in converses.values()],
    )
    check(
        "Converse では停止理由の呼び方が統一される",
        {r["stopReason"] for r in converses.values()} == {"end_turn"},
        {f: r["stopReason"] for f, r in converses.items()},
    )
    check(
        "Converse の計測値もネイティブ形式と一致する",
        all(
            (r["inputTokens"], r["outputTokens"], r["latencyMs"])
            == (EXPECTED_INPUT_TOKENS, EXPECTED_OUTPUT_TOKENS, EXPECTED_LATENCY_MS)
            for r in converses.values()
        ),
        {f: (r["inputTokens"], r["outputTokens"], r["latencyMs"]) for f, r in converses.items()},
    )
    check(
        "Meta 形式のネイティブ回答と Converse の回答は同一",
        natives["meta"]["text"] == converses["meta"]["text"],
        natives["meta"]["text"][:20],
    )

    # ------------------------------------------------------------------
    section("4. 検証関数（正規化 → 遮断）")
    records = ingest_pipeline.load_records()
    results = input_guard.check_all(records)
    by_id = {r.doc_id: r for r in results}

    check("バッチは18件（正常12＋壊れ6）", len(records) == 18, len(records))
    good = [r for r in results if r.doc_id in {d["id"] for d in ingest_pipeline.load_good_records()}]
    check(
        "正常な12件はすべて受理され、修復も不要",
        len(good) == 12 and all(r.status == "accepted" and not r.repairs for r in good),
        [(r.doc_id, r.status, r.repairs) for r in good if r.status != "accepted" or r.repairs],
    )
    check(
        "空文字は empty で遮断",
        by_id["bad-001"].rules == ("empty",),
        by_id["bad-001"].details,
    )
    check(
        "巨大テキストは too_long で遮断",
        by_id["bad-002"].rules == ("too_long",)
        and by_id["bad-002"].tokens > input_guard.MAX_INPUT_TOKENS,
        (by_id["bad-002"].rules, by_id["bad-002"].tokens),
    )
    check(
        "PII は3種すべて検出される",
        by_id["bad-003"].rules == ("pii",)
        and set(by_id["bad-003"].details) == {"pii:email", "pii:phone", "pii:long_digits"},
        by_id["bad-003"].details,
    )
    check(
        "全角英数は遮断せず NFKC で修復して通す",
        by_id["bad-004"].status == "accepted"
        and "nfkc" in by_id["bad-004"].repairs
        and "VPN" in by_id["bad-004"].text
        and "Windows11" in by_id["bad-004"].text,
        (by_id["bad-004"].status, by_id["bad-004"].repairs, by_id["bad-004"].text),
    )
    check(
        "正規化後に一致するコピーは duplicate で遮断",
        by_id["bad-005"].rules == ("duplicate",)
        and by_id["bad-005"].text == by_id["hr-001"].text,
        (by_id["bad-005"].rules, by_id["bad-005"].repairs),
    )
    check(
        "文字化けは修復せず mojibake で遮断",
        by_id["bad-006"].rules == ("mojibake",),
        by_id["bad-006"].details,
    )
    check(
        "受理された文書はすべて入力予算に収まっている",
        all(
            r.tokens <= input_guard.MAX_INPUT_TOKENS
            for r in results
            if r.status == "accepted"
        ),
        [(r.doc_id, r.tokens) for r in results if r.status == "accepted"],
    )

    # ------------------------------------------------------------------
    section("5. 隔離ストア（S3）と再処理キュー（SQS）")
    s3, sqs, queue_url = ingest_pipeline.ensure_resources()
    drain_queue(sqs, queue_url)  # 前回の実行分を空にしてから計測する

    summary = ingest_pipeline.run(run_id=RUN_ID)
    for key, expected in EXPECTED_SUMMARY.items():
        check(f"集計の {key} が {expected}", summary[key] == expected, summary[key])
    check("規則ごとの内訳が一致", summary["byRule"] == EXPECTED_BY_RULE, summary["byRule"])

    listed = s3.list_objects_v2(
        Bucket=ingest_pipeline.QUARANTINE_BUCKET, Prefix=summary["prefix"]
    )
    keys = {obj["Key"].rsplit("/", 1)[-1] for obj in listed.get("Contents", [])}
    check(
        "隔離ストアに5件の検知レコードが置かれる",
        keys == {f"{doc_id}.json" for doc_id in EXPECTED_QUARANTINED_IDS},
        sorted(keys),
    )

    messages = drain_queue(sqs, queue_url)
    mine = [m for m in messages if m.get("runId") == RUN_ID]
    check("再処理キューに5通届く", len(mine) == 5, len(messages))
    check(
        "各メッセージが規則と原本の所在を持つ",
        all(m["rules"] and m["sourceUri"].startswith("s3://") for m in mine),
        [(m["docId"], m["rules"]) for m in mine],
    )
    check(
        "隔離レコードに本文を含めていない",
        all("text" not in m for m in mine),
        [sorted(m) for m in mine[:1]],
    )
    body_dump = json.dumps(mine, ensure_ascii=False)
    check(
        "機密情報を隔離側へ複製していない",
        all(literal not in body_dump for literal in PII_LITERALS),
        body_dump[:80],
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション3の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
