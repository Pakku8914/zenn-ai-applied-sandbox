#!/usr/bin/env python3
"""セッション17の検証。

    docker compose exec app python src/session17/verify.py

**期待値と一致しなければ非0で終了します。** 時間の絶対値は環境で変わるため、
判定に使うのは次のものだけです。

    * レイテンシ予算の**計算**（仮定値からの積み上げ）
    * モックの決定的な規則（申告レイテンシ ＝ 20 + 出力トークン）から導ける値
    * 注入量（`latency_ms`）との大小関係
    * 索引を使った／使わなかったという**実行計画の違い**（実行時間では判定しない）
    * 集計値（母数・割合・命中率）と、CloudWatch へ書いて読み戻せたか
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session09")
sys.path.insert(0, "/workspace/src/session10")
sys.path.insert(0, "/workspace/src/session14")
sys.path.insert(0, "/workspace/src/session16")
sys.path.insert(0, "/workspace/src/session17")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import answer_cache  # noqa: E402
import continuous_monitoring as monitoring  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402
import provenance  # noqa: E402
import streaming  # noqa: E402
import vector_store  # noqa: E402

import latency_lab  # noqa: E402
import perf_metrics  # noqa: E402
import retrieval_perf  # noqa: E402
import tool_baseline  # noqa: E402

FAILURES: list[str] = []

MICRO = "amazon.nova-micro-v1:0"
LITE = "amazon.nova-lite-v1:0"
PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
LLAMA = "meta.llama3-3-70b-instruct-v1:0"
EMBED = "amazon.titan-embed-text-v2:0"

FLOOR = latency_lab.INJECT_FLOOR_MS

EXPECTED_METRICS = [
    "CacheHitRate",
    "ExhaustedRate",
    "GuardrailBlockRate",
    "InputTokens",
    "LatencyP50",
    "LatencyP95",
    "OutputTokens",
    "PromptEffectiveness",
    "RequestCount",
    "ZeroCitationRate",
]

FIRST_DELTA = "提供された資料によると、"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def raises(kind, fn) -> bool:
    try:
        fn()
    except kind:
        return True
    except Exception:  # noqa: BLE001 - 想定外の例外は失敗として扱う
        return False
    return False


def main() -> int:
    # 前セッションの障害注入が残っていると落ちるため、必ず最初に戻す
    model_router.reset_mock()
    runtime = clients.bedrock_runtime()
    ddb = answer_cache.ensure_table()
    answer_cache.clear(ddb)
    question, source = poc_probe.QUESTIONS[0]

    # ------------------------------------------------------------------
    section("1. レイテンシ予算（仮定値からの積み上げ）")
    serial = latency_lab.budget_ms()
    parallel = latency_lab.budget_ms(parallel_search=True)
    precomputed = latency_lab.budget_ms(parallel_search=True, precomputed_query=True)
    perceived = latency_lab.budget_ms(
        parallel_search=True, precomputed_query=True, until_first_delta=True
    )
    check("直列の合計は 1240 ms", serial == 1240, serial)
    check("検索2本を並列にすると 1210 ms", parallel == 1210, parallel)
    check("並列化で買えるのは遅い1本ぶんだけ（30 ms）", serial - parallel == 30,
          serial - parallel)
    check("クエリ前処理を事前計算すると 1090 ms", precomputed == 1090, precomputed)
    check("ストリーミングの体感は 485 ms", perceived == 485, perceived)
    check("事前計算が命中したときは 10 ms", latency_lab.cache_hit_ms() == 10,
          latency_lab.cache_hit_ms())
    rows = {row["tag"]: row for row in latency_lab.scenarios()}
    check(
        "ストリーミングは完了までを縮めない（S2 と S3 の完了が同じ）",
        rows["S3"]["total"] == rows["S2"]["total"] == 1090,
        (rows["S3"]["total"], rows["S2"]["total"]),
    )
    check(
        "出口ガードレールを全文に掛けると体感の利得が消える",
        rows["S3'"]["perceived"] == rows["S3'"]["total"] == 1090,
        rows["S3'"],
    )
    check(
        "事前計算だけが体感と完了の両方を縮める",
        rows["S4"]["perceived"] == rows["S4"]["total"] == 10,
        rows["S4"],
    )

    # ------------------------------------------------------------------
    section("2. 差分がいつ出来上がるか（モックの規則から導く）")
    reference = streaming.sync_answer(runtime, question, source)
    clock = latency_lab.token_clock(reference["text"])
    check("答えは 70 文字", clock["chars"] == 70, clock["chars"])
    check("出力は 66 トークン", clock["outputTokens"] == 66, clock["outputTokens"])
    check(
        "API の usage も 66 トークン（見積もりと一致）",
        reference["usage"]["outputTokens"] == clock["outputTokens"],
        reference["usage"],
    )
    check("12文字ずつ6個の差分に分かれる", clock["pieces"] == 6, clock["pieces"])
    check(f"最初の差分は「{FIRST_DELTA}」", clock["firstPiece"] == FIRST_DELTA,
          clock["firstPiece"])
    check("最初の差分は 12 トークン", clock["firstDeltaTokens"] == 12,
          clock["firstDeltaTokens"])
    check("最初の差分が出来上がるまで 32 ms", clock["modelFirstMs"] == 32,
          clock["modelFirstMs"])
    check("全文が出来上がるまで 86 ms", clock["modelTotalMs"] == 86,
          clock["modelTotalMs"])
    check(
        "API が申告するレイテンシも 86 ms（20 + 出力トークン）",
        reference["reportedLatencyMs"] == 86,
        reference["reportedLatencyMs"],
    )
    check("初回差分は完了より早く出来上がる",
          clock["modelFirstMs"] < clock["modelTotalMs"])

    # ------------------------------------------------------------------
    section("3. 同じ質問を3経路で流す（上流の待ちを注入）")
    outcome = latency_lab.run_routes(runtime, ddb, question, source)
    routes = {row["tag"]: row for row in outcome["routes"]}
    check("注入量は 600 ms", outcome["injectMs"] == 600, outcome["injectMs"])
    check("A はモデルを1回呼ぶ", routes["A"]["calls"] == 1, routes["A"]["calls"])
    check("B はモデルを1回呼ぶ", routes["B"]["calls"] == 1, routes["B"]["calls"])
    check("C はモデルを1回も呼ばない", routes["C"]["calls"] == 0, routes["C"]["calls"])
    check(
        "A は初回差分＝完了（全文が揃うまで何も出せない）",
        routes["A"]["firstDeltaMs"] == routes["A"]["totalMs"],
        routes["A"]["firstDeltaMs"],
    )
    check("A の完了は注入量以上", routes["A"]["totalMs"] >= FLOOR, routes["A"]["totalMs"])
    check(
        "B の初回差分も注入量以上（上流の待ちはストリーミングでも隠せない）",
        routes["B"]["firstDeltaMs"] >= FLOOR,
        routes["B"]["firstDeltaMs"],
    )
    check("B の初回差分は完了以前", routes["B"]["firstDeltaMs"] <= routes["B"]["totalMs"],
          (routes["B"]["firstDeltaMs"], routes["B"]["totalMs"]))
    check(
        "C は注入量を待たない（呼んでいないため）",
        routes["C"]["totalMs"] < FLOOR,
        routes["C"]["totalMs"],
    )
    check("C は初回差分＝完了（全文を一度に返す）",
          routes["C"]["firstDeltaMs"] == routes["C"]["totalMs"])
    check("3経路の本文は一致する",
          len({row["text"] for row in outcome["routes"]}) == 1)
    check(
        "申告レイテンシは注入で変わらない（86 ms のまま）",
        routes["A"]["reportedLatencyMs"] == 86,
        routes["A"]["reportedLatencyMs"],
    )
    behavior = model_router.set_behavior()
    check("計測が終わったら注入を戻している", behavior["latency_ms"] == 0, behavior)

    # ------------------------------------------------------------------
    section("4. レイテンシ最適化モデルの選び分け")
    groups = latency_lab.models_by_latency_class()
    check("optimized は3件（Micro / Lite / Haiku）",
          groups["optimized"] == [MICRO, LITE, HAIKU], groups["optimized"])
    check("standard は3件（Pro / Sonnet / Llama）",
          groups["standard"] == [PRO, SONNET, LLAMA], groups["standard"])
    check("対話 × 分類は Nova Micro",
          latency_lab.pick_model("interactive", "classify") == MICRO)
    check("対話 × 回答は Nova Lite",
          latency_lab.pick_model("interactive", "answer") == LITE)
    check("バッチ × 推論の質は Claude Sonnet 4.5",
          latency_lab.pick_model("batch", "reason") == SONNET)
    check("未定義の組み合わせは KeyError",
          raises(KeyError, lambda: latency_lab.pick_model("interactive", "openweight")))
    check(
        "対話向けの宛先はすべて optimized",
        all(
            latency_lab.latency_class_of(model_id) == "optimized"
            for mode, _t, _l, model_id in latency_lab.LATENCY_ROUTES
            if mode == "interactive"
        ),
    )
    check(
        "対話経路に standard を置いた表を弾く",
        raises(
            ValueError,
            lambda: latency_lab.validate_routes(
                (("interactive", "answer", "対話 × 回答", PRO),)
            ),
        ),
    )
    check(
        "カタログに無いモデル ID を弾く",
        raises(
            ValueError,
            lambda: latency_lab.validate_routes(
                (("batch", "answer", "バッチ × 回答", "openai.gpt-5"),)
            ),
        ),
    )
    check(
        "Converse 非対応（埋め込み）を弾く",
        raises(
            ValueError,
            lambda: latency_lab.validate_routes(
                (("batch", "answer", "バッチ × 回答", EMBED),)
            ),
        ),
    )
    lite_usd = catalog.cost_usd(LITE, *latency_lab.REFERENCE_WORKLOAD)
    haiku_usd = catalog.cost_usd(HAIKU, *latency_lab.REFERENCE_WORKLOAD)
    check("参照ワークロード1回は Lite 0.000132 / Haiku 0.002000 USD",
          f"{lite_usd:.6f}" == "0.000132" and f"{haiku_usd:.6f}" == "0.002000",
          (lite_usd, haiku_usd))
    check("同じ optimized でも単価は 15.2倍ちがう",
          f"{haiku_usd / lite_usd:.1f}" == "15.2", haiku_usd / lite_usd)

    # ------------------------------------------------------------------
    section("5. よくある質問を事前計算で受ける")
    records = latency_lab.run_cache_stream(runtime, ddb)
    stats = latency_lab.cache_stats(records)
    check(
        "6件の内訳は model cache model cache cache model",
        latency_lab.served_marks(records) == "model cache model cache cache model",
        latency_lab.served_marks(records),
    )
    check("命中は3件", stats["hits"] == 3, stats["hits"])
    check("引いた回数は6回", stats["lookups"] == 6, stats["lookups"])
    check("命中率は 0.5", stats["hitRate"] == 0.5, stats["hitRate"])
    check("モデルの呼び出しは3回", stats["calls"] == 3, stats["calls"])
    check(
        "命中した件の本文は、作ったときの本文と同じ",
        len({record["text"] for record in records if record["qid"] == "q0"}) == 1,
    )

    # ------------------------------------------------------------------
    section("6. 検索側の性能（実行計画で判定する）")
    conn = vector_store.connect()
    try:
        state = retrieval_perf.baseline(conn, runtime)
        check("行数は 12（1文書=1チャンク）", state["rows"] == 12, state["rows"])
        check("次元は 1024", state["dims"] == 1024, state["dims"])
        check("埋め込みが空の行は 0", state["missingEmbedding"] == 0,
              state["missingEmbedding"])
        check("doc_id の重複は 0", state["duplicatedDocIds"] == 0,
              state["duplicatedDocIds"])
        check("カテゴリは 4種", state["categories"] == 4, state["categories"])
        check("HNSW 索引がある", retrieval_perf.HNSW_INDEX in state["indexes"],
              sorted(state["indexes"]))
        check(
            "HNSW 索引の演算子クラスは vector_cosine_ops",
            "vector_cosine_ops" in state["indexes"][retrieval_perf.HNSW_INDEX],
            state["indexes"].get(retrieval_perf.HNSW_INDEX),
        )
        check(
            "メタデータ列にも索引がある",
            set(retrieval_perf.META_INDEXES) <= set(state["indexes"]),
            sorted(state["indexes"]),
        )

        compared = retrieval_perf.compare_plans(conn, runtime)
        with_index = compared["withIndex"]
        without_index = compared["withoutIndex"]
        check("索引ありは Index Scan", with_index["nodeType"] == "Index Scan",
              with_index["nodeTypes"])
        check("使われた索引は HNSW",
              with_index["indexName"] == retrieval_perf.HNSW_INDEX,
              with_index["indexName"])
        check("索引ありは並べ替えが要らない", with_index["sorted"] is False,
              with_index["nodeTypes"])
        check("索引なしは Seq Scan", without_index["nodeType"] == "Seq Scan",
              without_index["nodeTypes"])
        check("索引なしは並べ替えが入る", without_index["sorted"] is True,
              without_index["nodeTypes"])
        check("どちらも3件返す",
              len(with_index["docIds"]) == len(without_index["docIds"]) == 3,
              (with_index["docIds"], without_index["docIds"]))
        check("12行では近似と厳密の結果が一致する", compared["sameResult"],
              (with_index["docIds"], without_index["docIds"]))

        counts = retrieval_perf.prefilter_counts(conn)
        check("カテゴリで絞ると母集団は 12 -> 3 になる",
              list(counts.values()) == [3, 3, 3, 3], counts)
        golden = retrieval_perf.golden_check(conn, runtime)
        check("定点クエリの1位は hr-001", golden["ok"], golden)
        check("上位3件が返る", golden["returned"] == 3, golden["returned"])
    finally:
        conn.close()

    # ------------------------------------------------------------------
    section("7. 生成AI固有の指標（集計・メトリクス・通知）")
    check("パーセンタイルは最近傍順位法",
          [perf_metrics.percentile(list(range(1, 11)), q) for q in (0.5, 0.9, 0.95)]
          == [5, 9, 10],
          [perf_metrics.percentile(list(range(1, 11)), q) for q in (0.5, 0.9, 0.95)])
    check("空なら 0", perf_metrics.percentile([], 0.95) == 0)

    window = perf_metrics.run_window(runtime=runtime, ddb=ddb)
    summary = perf_metrics.summarize(window["entries"], cache=window["cache"])
    check("観測窓は10件", summary["total"] == 10, summary["total"])
    check("入口を通ったのは9件", summary["attempted"] == 9, summary["attempted"])
    check("モデルを呼んだのは7件", summary["modelCalled"] == 7, summary["modelCalled"])
    check("一次モデルで通ったのは6件", summary["firstAttemptOk"] == 6,
          summary["firstAttemptOk"])
    check("拒否率は 0.1", summary["blockedRate"] == 0.1, summary["blockedRate"])
    check("引用ゼロ率は 0.2222", summary["zeroCitationRate"] == 0.2222,
          summary["zeroCitationRate"])
    check("exhausted率は 0.1111", summary["exhaustedRate"] == 0.1111,
          summary["exhaustedRate"])
    check("根拠提示率は 0.6667", summary["groundedRate"] == 0.6667,
          summary["groundedRate"])
    check("プロンプト有効性は 0.8571（6/7）",
          summary["promptEffectiveness"] == 0.8571, summary["promptEffectiveness"])
    check("キャッシュ命中率は 0.5", summary["cacheHitRate"] == 0.5,
          summary["cacheHitRate"])
    check("トークンは両方とも0より大きい",
          summary["inputTokens"] > 0 and summary["outputTokens"] > 0,
          (summary["inputTokens"], summary["outputTokens"]))
    check("レイテンシは p95 ≧ p50 > 0",
          summary["latencyP95Ms"] >= summary["latencyP50Ms"] > 0,
          (summary["latencyP50Ms"], summary["latencyP95Ms"]))
    check(
        "p95 はモデルの出力上限から決まる範囲に収まる（2 × (20 + 300)）",
        summary["latencyP95Ms"] <= 2 * (latency_lab.BASE_LATENCY_MS + 300),
        summary["latencyP95Ms"],
    )

    cw = clients.aws("cloudwatch")
    published = perf_metrics.publish_metrics(cw, summary, run_id=window["runId"])
    check("メトリクスは10本", sorted(published) == EXPECTED_METRICS, sorted(published))
    listed = perf_metrics.listed_metrics(cw, run_id=window["runId"])
    check("書いたメトリクスが読み戻せる", listed == EXPECTED_METRICS, listed)
    total_points = perf_metrics.read_sum(
        cw, perf_metrics.COUNT_METRIC, run_id=window["runId"]
    )
    check("母数のメトリクスの値が集計と一致する",
          total_points == float(summary["total"]), total_points)

    found = perf_metrics.breaches(summary)
    check(
        "逸脱は3件（命中率・プロンプト有効性・引用ゼロ率）",
        [breach["metricName"] for breach in found]
        == ["CacheHitRate", "PromptEffectiveness", "ZeroCitationRate"],
        [breach["metricName"] for breach in found],
    )
    check(
        "下限を割った項目は min 方向で判定されている",
        {b["metricName"]: b["direction"] for b in found}
        == {"CacheHitRate": "min", "PromptEffectiveness": "min",
            "ZeroCitationRate": "max"},
        [(b["metricName"], b["direction"]) for b in found],
    )
    check(
        "レイテンシ p95 はしきい値の内側なので通知しない",
        "LatencyP95" not in {breach["metricName"] for breach in found},
        summary["latencyP95Ms"],
    )

    channels = monitoring.ensure_channels()
    monitoring.drain(channels["inboxUrl"])
    sent = perf_metrics.notify_perf(
        found, summary, channels=channels, run_id=window["runId"]
    )
    check("逸脱ぶんだけ通知する", sent == len(found) == 3, sent)
    inbox = monitoring.receive(channels["inboxUrl"], expected=sent)
    check("人向けの通知（SNS）が届く", len(inbox) == sent, len(inbox))
    payloads = [json.loads(message["Body"]) for message in inbox]
    check(
        "通知に指標・値・しきい値・母数・次の手が入る",
        all({"metric", "value", "threshold", "window", "action"} <= set(payload)
            for payload in payloads),
        [sorted(payload) for payload in payloads][:1],
    )
    check(
        "通知に本文は入っていない",
        all(
            scenario["question"] not in json.dumps(payloads, ensure_ascii=False)
            for scenario in provenance.SCENARIOS
        ),
    )
    monitoring.drain(channels["inboxUrl"])
    quiet = perf_metrics.notify_perf(
        [], summary, channels=channels, run_id=window["runId"]
    )
    check("逸脱が無ければ1通も送らない", quiet == 0, quiet)

    # ------------------------------------------------------------------
    section("8. ツール呼び出しのベースラインからの逸脱")
    report = tool_baseline.deviations()
    check(
        "今日の割合は 0.5333 / 0.1333 / 0.3333",
        [row["observed"] for row in report["rows"]] == [0.5333, 0.1333, 0.3333],
        [row["observed"] for row in report["rows"]],
    )
    check(
        "平常との差は -0.0667 / -0.1667 / 0.2333",
        [row["delta"] for row in report["rows"]] == [-0.0667, -0.1667, 0.2333],
        [row["delta"] for row in report["rows"]],
    )
    check(
        "逸脱したのは lookup_ticket と escalate",
        report["deviatedTools"] == ["lookup_ticket", "escalate"],
        report["deviatedTools"],
    )
    check("1件あたりの往復は 3.0 回", report["callsPerRequest"] == 3.0,
          report["callsPerRequest"])
    check("平常の 1.5倍で上限超え", report["callsRatio"] == 1.5
          and report["callsDeviated"], report["callsRatio"])
    check("同じツールの最長連続は 3 回", report["longestRepeat"] == 3,
          report["longestRepeat"])
    check("連続の上限を超えている", report["repeatDeviated"])
    check("連続していなければ 1 回",
          tool_baseline.longest_repeat(("search_docs", "escalate", "search_docs")) == 1)
    check("軌跡が空なら 0 回", tool_baseline.longest_repeat(()) == 0)
    check(
        "件数が2倍になっても割合は動かない（利用増で誤検知しない）",
        tool_baseline.shares({k: v * 2 for k, v in tool_baseline.OBSERVED_CALLS.items()})
        == tool_baseline.shares(tool_baseline.OBSERVED_CALLS),
    )

    # ------------------------------------------------------------------
    section("9. 後片付け")
    behavior = model_router.set_behavior()
    check("レイテンシ注入は解除されている", behavior["latency_ms"] == 0, behavior)
    answer_cache.clear(ddb)
    check("キャッシュを空にした", answer_cache.count(ddb) == 0, answer_cache.count(ddb))
    model_router.reset_mock()
    check("モックの会計を初期化した", model_router.mock_usage()["calls"] == 0)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション17の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
