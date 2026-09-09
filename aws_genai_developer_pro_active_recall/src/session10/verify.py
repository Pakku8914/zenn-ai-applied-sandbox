#!/usr/bin/env python3
"""セッション10の検証。

「差分の連結が非ストリーミングの本文と一致すること」
「初回差分は完了より早く届くが、上流の待ちはストリーミングでも隠せないこと」
「`max_attempts` と `mode` で結果が変わること」
「内容に応じたルーティングが1件1回で完結すること」
「相関 ID がサービス境界を越えて引き継がれること」を確認します。
**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session10/verify.py

時間の絶対値は環境で変わるため、検証は**大小関係**で行います。
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session10")

from botocore.exceptions import ClientError  # noqa: E402

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import content_router  # noqa: E402
import delivery  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402
import retry_lab  # noqa: E402
import streaming  # noqa: E402

FAILURES: list[str] = []

LITE = "amazon.nova-lite-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
LLAMA = "meta.llama3-3-70b-instruct-v1:0"
MICRO = "amazon.nova-micro-v1:0"
PRO = "amazon.nova-pro-v1:0"
EMBED = "amazon.titan-embed-text-v2:0"

# 注入するレイテンシ（ミリ秒）。sleep は必ずこの時間以上待つので、
# 9割を下限にしておけば計測の揺れで落ちない
LATENCY_MS = 300
LATENCY_FLOOR = LATENCY_MS * 0.9


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:  # noqa: BLE001 - 想定外の例外は失敗として扱う
        return False
    return False


def main() -> int:
    # 前セッションの障害注入が残っていると落ちるため、必ず最初にリセットする
    model_router.reset_mock()
    runtime = clients.bedrock_runtime()
    question, source = poc_probe.QUESTIONS[0]

    # ------------------------------------------------------------------
    section("1. ConverseStream のイベント順と、差分の一致")
    sync = streaming.sync_answer(runtime, question, source)
    streamed = streaming.stream_answer(runtime, question, source)
    names = streamed["eventNames"]
    check("最初のイベントは messageStart", names[0] == "messageStart", names[:2])
    check("最後のイベントは metadata", names[-1] == "metadata", names[-2:])
    check("messageStop は metadata の直前", names[-2] == "messageStop", names[-3:])
    check("contentBlockStop が届く", "contentBlockStop" in names, names)
    check("差分は2つ以上に分かれて届く", len(streamed["deltas"]) >= 2,
          len(streamed["deltas"]))
    check(
        "差分を連結すると非ストリーミングの本文と完全に一致する",
        streamed["text"] == sync["text"],
        (streamed["text"][:20], sync["text"][:20]),
    )
    check("stopReason はどちらも end_turn",
          streamed["stopReason"] == sync["stopReason"] == "end_turn",
          (streamed["stopReason"], sync["stopReason"]))
    check(
        "metadata の usage は非ストリーミングと一致する",
        streamed["usage"]["outputTokens"] == sync["usage"]["outputTokens"],
        (streamed["usage"], sync["usage"]),
    )
    check(
        "申告レイテンシ（metrics.latencyMs）も一致する",
        streamed["reportedLatencyMs"] == sync["reportedLatencyMs"],
        (streamed["reportedLatencyMs"], sync["reportedLatencyMs"]),
    )

    # ------------------------------------------------------------------
    section("2. モデル系統が変わってもイベントの形は変わらない")
    for model_id in (HAIKU, LLAMA):
        other = streaming.stream_answer(runtime, question, source, model_id=model_id)
        check(
            f"{model_id} も同じ種類のイベントを返す",
            set(other["eventNames"]) == set(names),
            sorted(set(other["eventNames"])),
        )

    # ------------------------------------------------------------------
    section("3. 時間は2つに分けて測る（初回差分 と 完了）")
    check(
        "初回差分は完了より早く届く",
        streamed["firstDeltaMs"] < streamed["totalMs"],
        (streamed["firstDeltaMs"], streamed["totalMs"]),
    )
    check(
        "最後の差分は完了以前に届く（metadata が後に来る）",
        streamed["lastDeltaMs"] <= streamed["totalMs"],
        (streamed["lastDeltaMs"], streamed["totalMs"]),
    )

    model_router.set_behavior(latency_ms=LATENCY_MS)
    slow_stream = streaming.stream_answer(runtime, question, source)
    slow_sync = streaming.sync_answer(runtime, question, source)
    # 注入したレイテンシを残すと後続の検証が遅くなる／落ちる
    model_router.reset_mock()
    fast_stream = streaming.stream_answer(runtime, question, source)

    check(
        "上流の待ちは初回差分までの時間に乗る（ストリーミングでも隠せない）",
        slow_stream["firstDeltaMs"] >= LATENCY_FLOOR,
        slow_stream["firstDeltaMs"],
    )
    check(
        "同期呼び出しも同じだけ待たされる",
        slow_sync["wallMs"] >= LATENCY_FLOOR,
        slow_sync["wallMs"],
    )
    check(
        "モデルが申告する latencyMs は待ちを含まない",
        slow_sync["reportedLatencyMs"] == sync["reportedLatencyMs"],
        (slow_sync["reportedLatencyMs"], sync["reportedLatencyMs"]),
    )
    check(
        "体感（wallMs）は申告レイテンシより大きい",
        slow_sync["wallMs"] > slow_sync["reportedLatencyMs"],
        (slow_sync["wallMs"], slow_sync["reportedLatencyMs"]),
    )
    check(
        "注入を解除すると初回差分は速くなる",
        fast_stream["firstDeltaMs"] < slow_stream["firstDeltaMs"],
        (fast_stream["firstDeltaMs"], slow_stream["firstDeltaMs"]),
    )
    check(
        "レイテンシ注入を解除できている",
        model_router.mock_usage()["calls"] >= 1,
        model_router.mock_usage()["calls"],
    )

    # ------------------------------------------------------------------
    section("4. InvokeModelWithResponseStream（二重構造）")
    native = streaming.native_stream(runtime, question, source)
    check(
        "message_start で始まり message_stop で終わる",
        native["types"][0] == "message_start" and native["types"][-1] == "message_stop",
        native["types"],
    )
    check("content_block_delta が複数届く",
          native["types"].count("content_block_delta") >= 2, native["types"])
    check("message_delta で stop_reason が届く",
          native["stopReason"] == "end_turn", native["stopReason"])
    check("Converse 系のイベント名は混ざらない",
          "messageStart" not in native["types"], native["types"])
    check("受け取れる本文は Converse と同じ", native["text"] == sync["text"])

    # ------------------------------------------------------------------
    section("5. ブラウザまで届ける（SSE の整形）")
    frames = streaming.sse_frames(
        streamed["deltas"], stop_reason=streamed["stopReason"]
    )
    check("フレーム数は 差分＋終了1", len(frames) == len(streamed["deltas"]) + 1,
          len(frames))
    check("すべてのフレームが空行で終わる", all(f.endswith("\n\n") for f in frames))
    check("1フレームに区切りは1つだけ", all(f.count("\n\n") == 1 for f in frames))
    check("受け取り側で本文を復元できる",
          streaming.text_from_sse(frames) == sync["text"])
    check("答えには改行が含まれている（素朴な整形が壊れる理由）",
          "\n" in sync["text"])
    naive = f"data: {sync['text']}\n\n"
    check("素朴に本文を流すと区切りが2つになる（フレームが割れる）",
          naive.count("\n\n") == 2, naive.count("\n\n"))

    # ------------------------------------------------------------------
    section("6. boto3 に任せるリトライ（mode と max_attempts）")
    for row in retry_lab.run_matrix(question, source):
        label = row["label"]
        if row["expectOutcome"] is not None:
            check(f"{label} の結果は {row['expectOutcome']}",
                  row["outcome"] == row["expectOutcome"], row["outcome"])
        if row["expectRequests"] is not None:
            check(f"{label} が受けた 429 は {row['expectRequests']}回",
                  row["requests"] == row["expectRequests"], row["requests"])
        # 実測では max_attempts=N に対して N+1 リクエストが飛ぶ。
        # 「仕様の記憶」ではなく throttled で数えることを検証で固定する
        check(f"{label} の試行は max_attempts + 1 回で止まる",
              1 <= row["requests"] <= row["maxAttempts"] + 1, row["requests"])

    # ------------------------------------------------------------------
    section("7. 自分で書くリトライ（指数バックオフとジッター）")
    windows = [retry_lab.backoff_window(i) for i in range(5)]
    check("窓は倍々に伸びる",
          windows[1] == windows[0] * 2 and windows[2] == windows[1] * 2, windows)
    check("窓は上限を超えない",
          all(w <= retry_lab.MAX_DELAY_SECONDS for w in windows), windows)
    check("上限に達したら伸びない", windows[4] == windows[3], windows[3:])

    jittered = retry_lab.backoff_plan(5, jitter=True, seed=11)
    check("ジッターは窓の中に収まる",
          all(0.0 <= d <= retry_lab.backoff_window(i)
              for i, d in enumerate(jittered)), jittered)
    check("ジッターありは値が散る", len(set(jittered)) == len(jittered), jittered)
    check("同じ seed なら再現する",
          retry_lab.backoff_plan(5, jitter=True, seed=11) == jittered)
    check("seed を変えると別の並びになる",
          retry_lab.backoff_plan(5, jitter=True, seed=12) != jittered)
    check(
        "ジッター無しは全員が同じ時刻に再送する（窓の値そのまま）",
        retry_lab.backoff_plan(3, jitter=False) == windows[:3],
        retry_lab.backoff_plan(3, jitter=False),
    )

    # SDK 側にもリトライが残っている（max_attempts=1 でも1回あたり2リクエスト）。
    # 自作の外側を3回回すには、注入するスロットリングは4回必要になる
    sdk_client = clients.bedrock_runtime(max_attempts=1)
    model_router.set_behavior(throttle_next=4)
    before = model_router.mock_usage()["throttled"]
    manual = retry_lab.call_with_backoff(
        sdk_client, question, source, rng=random.Random(7)
    )
    after = model_router.mock_usage()["throttled"]
    check("失敗が続いても自作のリトライで回復する", manual["outcome"] == "ok", manual)
    check("自作の試行は3回（初回＋再試行2回）",
          manual["attempts"] == 3, manual["attempts"])
    check("自作が待ったのは2回", len(manual["waited"]) == 2, manual["waited"])
    check("待ち時間はすべて窓の中に収まっている",
          all(0.0 <= d <= retry_lab.backoff_window(i)
              for i, d in enumerate(manual["waited"])), manual["waited"])
    check("リトライを重ねるとリクエスト数は掛け算になる（429 は4回）",
          after - before == 4, after - before)
    check("回復後の本文は同期と同じ", manual["text"] == sync["text"])

    model_router.set_behavior(throttle_next=8)
    exhausted = retry_lab.call_with_backoff(
        sdk_client, question, source, max_attempts=2, rng=random.Random(7)
    )
    check("上限に達したら諦めてエラーを返す",
          exhausted["outcome"] == "ThrottlingException", exhausted)
    check("諦めるまでの試行回数は max_attempts と同じ",
          exhausted["attempts"] == 2, exhausted["attempts"])
    model_router.set_behavior(throttle_next=0)

    check("セッション2の FATAL_CODES を再利用している",
          "ValidationException" in model_router.FATAL_CODES,
          sorted(model_router.FATAL_CODES))
    model_router.set_behavior(force_validation_error=True)
    fatal_code = None
    try:
        retry_lab.call_with_backoff(sdk_client, question, source)
    except ClientError as error:
        fatal_code = error.response["Error"]["Code"]
    check("リトライで直らないエラーは待たずにそのまま返す",
          fatal_code == "ValidationException", fatal_code)
    model_router.reset_mock()

    # ------------------------------------------------------------------
    section("8. 内容に応じたモデルルーティング")
    content_router.validate_routes()
    decisions = [content_router.route(r) for r in content_router.WORKLOAD]
    actual = [(d["requestId"], d["reason"], d["modelId"]) for d in decisions]
    check("8件の振り分けが期待どおり",
          actual == content_router.EXPECTED_ROUTES, actual)
    image_model = next(d["modelId"] for d in decisions if d["reason"] == "needs_image")
    check("画像つきの依頼は画像を扱えるモデルへ行く",
          "IMAGE" in catalog.resolve(image_model)[0].modality, image_model)
    long_ids = [d["requestId"] for d in decisions if d["reason"] == "long_input"]
    check("長い入力だけが long_input になる", long_ids == ["api-006"], long_ids)
    check(
        "見積もりトークン数が閾値をまたいでいる",
        min(d["estimatedInputTokens"] for d in decisions if d["reason"] == "long_input")
        > content_router.LONG_INPUT_TOKENS
        >= max(d["estimatedInputTokens"] for d in decisions
               if d["reason"] != "long_input"),
        [d["estimatedInputTokens"] for d in decisions],
    )

    check(
        "画像を扱えない宛先を弾く",
        raises_value_error(
            lambda: content_router.validate_routes(
                {**content_router.ROUTE_MODELS, "needs_image": MICRO}
            )
        ),
    )
    check(
        "カタログに無いモデル ID を弾く",
        raises_value_error(
            lambda: content_router.validate_routes(
                {**content_router.ROUTE_MODELS, "default": "openai.gpt-5"}
            )
        ),
    )
    check(
        "Converse 非対応（埋め込み）の宛先を弾く",
        raises_value_error(
            lambda: content_router.validate_routes(
                {**content_router.ROUTE_MODELS, "default": EMBED}
            )
        ),
    )
    check(
        "代替先が同じプロバイダの表を弾く",
        raises_value_error(
            lambda: content_router.validate_routes(
                None, {**content_router.FALLBACK_OF, LITE: [PRO]}
            )
        ),
    )

    model_router.reset_mock()
    router = model_router.ModelRouter(config=model_router.bootstrap())
    served = content_router.serve_all(content_router.WORKLOAD, router)
    usage = model_router.mock_usage()
    check("依頼1件につきモデルの呼び出しは1回",
          usage["calls"] == len(content_router.WORKLOAD), usage["calls"])
    check("宛先どおりのモデルが答えた",
          all(s["servedBy"] == s["modelId"] for s in served),
          [(s["modelId"], s["servedBy"]) for s in served])
    check("縮退も代替も起きていない",
          all(s["result"]["serviceLevel"] == "full" for s in served),
          [s["result"]["serviceLevel"] for s in served])
    spread = content_router.distribution(served)
    check("4つのモデルに分散した", len(spread) == 4, spread)
    check("資料つきの依頼は根拠を提示できている",
          all(served[i]["result"]["grounded"] for i in (1, 5, 7)),
          [served[i]["result"]["grounded"] for i in (1, 5, 7)])

    # ------------------------------------------------------------------
    section("9. 同期・非同期・ストリーミングと相関 ID の伝播")
    model_router.reset_mock()
    infra = delivery.ensure_infra()
    sqs, ddb, logs, queue_url = infra
    delivery.purge(sqs, queue_url)
    router = model_router.ModelRouter(config=model_router.bootstrap())
    request = {"question": question, "context": source}

    accepted = delivery.submit(request, infra=infra)
    check("受付の時点でモデルを呼んでいない",
          model_router.mock_usage()["calls"] == 0,
          model_router.mock_usage()["calls"])
    check("受付 ID を即座に返す", len(accepted["jobId"]) == 12, accepted)
    check("受付直後の状態は accepted",
          delivery.get_job(accepted["jobId"], ddb=ddb)["status"] == "accepted")

    processed = delivery.work_off(router, infra=infra, expected=1)
    check("1件処理した", len(processed) == 1, len(processed))
    check("処理側は受付側の traceId を引き継ぐ",
          processed[0]["traceId"] == accepted["traceId"],
          (processed[0]["traceId"], accepted["traceId"]))
    check("処理後の状態は done",
          delivery.get_job(accepted["jobId"], ddb=ddb)["status"] == "done")
    check("非同期でもモデルの呼び出しは1回",
          model_router.mock_usage()["calls"] == 1,
          model_router.mock_usage()["calls"])
    left = sqs.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1
    ).get("Messages", [])
    check("キューが空になった", not left, left)

    sync_served = delivery.serve_sync(request, router, infra=infra)
    stream_served = delivery.serve_stream(
        request, clients.bedrock_runtime(), infra=infra
    )
    check(
        "3経路の本文が一致する（待たせ方だけが違う）",
        sync_served["text"] == processed[0]["text"] == stream_served["text"],
    )
    check(
        "ストリーミングは初回差分が完了より早い",
        stream_served["firstDeltaMs"] < stream_served["totalMs"],
        (stream_served["firstDeltaMs"], stream_served["totalMs"]),
    )

    records = delivery.read_trace(logs, accepted["traceId"])
    check("同じ traceId で2件の記録が残る", len(records) == 2, len(records))
    check("入口と処理側の両方が記録されている",
          {r["stage"] for r in records} == {"accepted", "worker"},
          [r["stage"] for r in records])
    check("すべての記録が同じ traceId を持つ",
          {r["traceId"] for r in records} == {accepted["traceId"]})
    check(
        "区間（span）の名前が残っている",
        {s["name"] for r in records for s in r["spans"]}
        == {"intake", "bedrock", "persist"},
        [r["spans"] for r in records],
    )
    check("プロンプト本文と回答本文はログに残していない",
          all("question" not in r and "answer" not in r for r in records),
          [sorted(r) for r in records])

    # 後続セッションのために状態を戻す
    model_router.reset_mock()
    model_router.put_config(model_router.DEFAULT_CONFIG)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション10の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
