#!/usr/bin/env python3
"""セッション16の検証。

「トークンの見積もりが API の実測値と一致すること」
「`cachePoint` の3欄の合計がプロンプト全体のトークン数と一致すること」
「5条件の費用が `GET /_mock/usage` の `estimatedUsd` と手元の計算で一致すること」
「セマンティックキャッシュがしきい値を緩めると誤ヒットすること」
「損益分岐の計算が単価から再現できること」を確認します。
**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session16/verify.py
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session09")
sys.path.insert(0, "/workspace/src/session16")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import answer_cache  # noqa: E402
import cascade  # noqa: E402
import cost_lab  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402
import throughput  # noqa: E402

FAILURES: list[str] = []

MICRO = "amazon.nova-micro-v1:0"
LITE = "amazon.nova-lite-v1:0"
PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
LLAMA = "meta.llama3-3-70b-instruct-v1:0"
EMBED = "amazon.titan-embed-text-v2:0"

estimate = cascade.token_estimate

# モックの生成器が返す文（決定的）。セッション1の資料をそのまま組み立てて作る
EXPECTED_ANSWER = (
    "提供された資料によると、"
    + poc_probe.QUESTIONS[0][1]
    + "\n\n（根拠: 検索で取得した資料内の記述）"
)
# 出力上限 20 トークンで打ち切られた場合に残る文
TRUNCATED_ANSWER = "提供された資料によると、年次有給休暇の未"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def usd(value: float) -> str:
    return f"{value:.6f}"


def ledger_usd(records: list[dict], model_id: str = LITE) -> float:
    """手元の台帳から費用を計算する（モックの会計と突き合わせるため）。"""
    served = [r for r in records if r["servedBy"] == "model"]
    return catalog.cost_usd(
        model_id,
        sum(r["inputTokens"] for r in served),
        sum(r["outputTokens"] for r in served),
    )


def main() -> int:
    # 前セッションの障害注入やキャッシュが残っていると落ちるため、必ず最初に戻す
    model_router.reset_mock()
    runtime = clients.bedrock_runtime()
    ddb = answer_cache.ensure_table()
    answer_cache.clear(ddb)

    # ------------------------------------------------------------------
    section("1. トークンの見積もりと2つの版")
    check(
        "冗長な版の system は 256 トークン",
        estimate(cost_lab.VERBOSE_SYSTEM) == 256,
        estimate(cost_lab.VERBOSE_SYSTEM),
    )
    check(
        "刈り込んだ版の system は 33 トークン",
        estimate(cost_lab.LEAN_SYSTEM) == 33,
        estimate(cost_lab.LEAN_SYSTEM),
    )
    check(
        "刈り込んだ版はセッション1の system と同一",
        cost_lab.LEAN_SYSTEM == poc_probe.SYSTEM_PROMPT,
    )
    verbose_system, verbose_blocks = cost_lab.build("q-carryover", compact=False)
    lean_system, lean_blocks = cost_lab.build("q-carryover", compact=True)
    verbose_one = cost_lab.call(
        runtime, verbose_system, verbose_blocks, max_tokens=512, cache=False
    )
    lean_one = cost_lab.call(
        runtime, lean_system, lean_blocks, max_tokens=120, cache=False
    )
    check(
        "無対策の入力は 395 トークン", verbose_one["inputTokens"] == 395, verbose_one["inputTokens"]
    )
    check("圧縮後の入力は 90 トークン（セッション1と同じ）",
          lean_one["inputTokens"] == 90, lean_one["inputTokens"])
    check(
        "呼ぶ前の見積もりが API の実測値と一致する（無対策）",
        verbose_one["estimate"] == verbose_one["promptTokens"],
        (verbose_one["estimate"], verbose_one["promptTokens"]),
    )
    check(
        "呼ぶ前の見積もりが API の実測値と一致する（圧縮後）",
        lean_one["estimate"] == lean_one["promptTokens"],
        (lean_one["estimate"], lean_one["promptTokens"]),
    )
    check("出力は 66 トークン（両方とも同じ）",
          verbose_one["outputTokens"] == 66 and lean_one["outputTokens"] == 66,
          (verbose_one["outputTokens"], lean_one["outputTokens"]))
    check("刈り込んでも答えは変わらない", lean_one["text"] == verbose_one["text"])
    check("答えは資料の1文だけを根拠にしている", lean_one["text"] == EXPECTED_ANSWER)
    check(
        "1件あたりの費用は 0.000040 -> 0.000021 USD",
        usd(catalog.cost_usd(LITE, 395, 66)) == "0.000040"
        and usd(catalog.cost_usd(LITE, 90, 66)) == "0.000021",
        (catalog.cost_usd(LITE, 395, 66), catalog.cost_usd(LITE, 90, 66)),
    )

    # ------------------------------------------------------------------
    section("2. cachePoint の3欄（合計は変わらない）")
    model_router.reset_mock()
    first = cost_lab.call(
        runtime, verbose_system, verbose_blocks, max_tokens=512, cache=True
    )
    second = cost_lab.call(
        runtime, verbose_system, verbose_blocks, max_tokens=512, cache=True
    )
    check("初回は書き込みだけが起きる",
          first["cacheWrite"] == 256 and first["cacheRead"] == 0, first)
    check("2回目は読み出しに振り替わる",
          second["cacheRead"] == 256 and second["cacheWrite"] == 0, second)
    check("請求対象の inputTokens はキャッシュ分だけ小さい",
          first["inputTokens"] == 139 and second["inputTokens"] == 139,
          (first["inputTokens"], second["inputTokens"]))
    check(
        "3欄の合計はプロンプト全体（395）と一致する",
        first["promptTokens"] == 395 and second["promptTokens"] == 395,
        (first["promptTokens"], second["promptTokens"]),
    )
    check(
        "cachePoint の有無で合計は変わらない",
        second["promptTokens"] == verbose_one["promptTokens"],
    )

    # ------------------------------------------------------------------
    section("3. 5条件の費用（GET /_mock/usage の estimatedUsd）")
    usage_a, records_a = cost_lab.measure(
        lambda: cost_lab.run_stream(runtime, compact=False, cache=False)
    )
    usage_b, records_b = cost_lab.measure(
        lambda: cost_lab.run_stream(runtime, compact=True, cache=False)
    )
    usage_c, records_c = cost_lab.measure(
        lambda: cost_lab.run_stream(runtime, compact=False, cache=True)
    )
    usage_d, records_d = cost_lab.measure(
        lambda: cost_lab.run_exact_cache(runtime, ddb), ddb=ddb
    )
    usage_e, outcome_e = cost_lab.measure(lambda: cost_lab.run_semantic_cache(runtime))
    records_e, semantic = outcome_e
    base = usage_a["estimatedUsdTotal"]

    for tag, want, usage in (
        ("A 無対策", "0.000304", usage_a),
        ("B 圧縮", "0.000158", usage_b),
        ("C 無対策＋プロンプトキャッシュ", "0.000181", usage_c),
        ("D 圧縮＋完全一致キャッシュ", "0.000077", usage_d),
        ("E 圧縮＋セマンティックキャッシュ", "0.000080", usage_e),
    ):
        check(
            f"{tag} の費用は {want} USD",
            usd(usage["estimatedUsdTotal"]) == want,
            usage["estimatedUsdTotal"],
        )

    for tag, want, usage, records in (
        ("A", 8, usage_a, records_a),
        ("B", 8, usage_b, records_b),
        ("C", 8, usage_c, records_c),
        ("D", 4, usage_d, records_d),
        ("E", 4, usage_e, records_e),
    ):
        calls = usage["perModel"].get(LITE, {}).get("calls", 0)
        check(f"{tag} のモデル呼び出しは {want}回", calls == want, calls)
        check(
            f"{tag} は手元の台帳とモックの会計が一致する",
            usd(ledger_usd(records)) == usd(usage["perModel"][LITE]["estimatedUsd"]),
            (ledger_usd(records), usage["perModel"][LITE]["estimatedUsd"]),
        )

    check("C の書き込みは初回の1回だけ（256トークン）",
          usage_c["cacheWriteTokens"] == 256, usage_c["cacheWriteTokens"])
    check("C の読み出しは残り7回ぶん（1,792トークン）",
          usage_c["cacheReadTokens"] == 1792, usage_c["cacheReadTokens"])
    check(
        "E の埋め込みは8回・142トークン",
        usage_e["perModel"][EMBED]["calls"] == 8
        and usage_e["perModel"][EMBED]["inputTokens"] == 142,
        usage_e["perModel"][EMBED],
    )
    check(
        "E の埋め込み費用が手元の計算と一致する",
        usd(
            catalog.cost_usd(
                EMBED, sum(estimate(cost_lab.QUESTIONS[q][0]) for q in cost_lab.STREAM), 0
            )
        )
        == usd(usage_e["perModel"][EMBED]["estimatedUsd"]),
        usage_e["perModel"][EMBED]["estimatedUsd"],
    )
    check("圧縮はキャッシュで殴るより効く（B < C）",
          usage_b["estimatedUsdTotal"] < usage_c["estimatedUsdTotal"],
          (usage_b["estimatedUsdTotal"], usage_c["estimatedUsdTotal"]))
    check("完全一致キャッシュは圧縮よりさらに効く（D < B）",
          usage_d["estimatedUsdTotal"] < usage_b["estimatedUsdTotal"])
    check(
        "厳しいしきい値のセマンティックキャッシュは埋め込み代のぶん高い（E > D）",
        usage_e["estimatedUsdTotal"] > usage_d["estimatedUsdTotal"],
        (usage_e["estimatedUsdTotal"], usage_d["estimatedUsdTotal"]),
    )
    check(
        "指数は A100 / B52 / C60 / D25 / E26",
        [
            round(u["estimatedUsdTotal"] / base * 100)
            for u in (usage_a, usage_b, usage_c, usage_d, usage_e)
        ]
        == [100, 52, 60, 25, 26],
        [
            round(u["estimatedUsdTotal"] / base * 100)
            for u in (usage_a, usage_b, usage_c, usage_d, usage_e)
        ],
    )
    check(
        "削る順番: 無対策は入力が費用の 61.8%、圧縮後は 26.4%",
        round(cost_lab.input_cost_share(usage_a), 3) == 0.618
        and round(cost_lab.input_cost_share(usage_b), 3) == 0.264,
        (cost_lab.input_cost_share(usage_a), cost_lab.input_cost_share(usage_b)),
    )
    check(
        "D と E はキャッシュから4件返している",
        [r["servedBy"] for r in records_d].count("cache") == 4
        and [r["servedBy"] for r in records_e].count("cache") == 4,
    )
    check("セマンティックキャッシュの登録は4件（言い換えは別項目になる）",
          semantic.size() == 4, semantic.size())

    # ------------------------------------------------------------------
    section("4. 出力上限は費用の制御ではなく事故の上限")
    model_router.reset_mock()
    capped = cost_lab.call(
        runtime, lean_system, lean_blocks, max_tokens=20, cache=False
    )
    check("出力は上限どおり 20 トークン", capped["outputTokens"] == 20, capped["outputTokens"])
    check("stopReason は max_tokens", capped["stopReason"] == "max_tokens",
          capped["stopReason"])
    check("答えは20文字で切れている", capped["text"] == EXPECTED_ANSWER[:20], capped["text"])
    check("打ち切られた文は本文に載せたとおり", capped["text"] == TRUNCATED_ANSWER,
          capped["text"])
    check("打ち切られた文のトークン数は 20", estimate(TRUNCATED_ANSWER) == 20,
          estimate(TRUNCATED_ANSWER))
    check(
        "費用は 0.000021 -> 0.000010 USD に下がる",
        usd(catalog.cost_usd(LITE, 90, 20)) == "0.000010",
        catalog.cost_usd(LITE, 90, 20),
    )
    check(
        "打ち切られても根拠の印は残る（印だけでは品質を測れない）",
        poc_probe.GROUNDING_MARKER in capped["text"],
    )

    # ------------------------------------------------------------------
    section("5. キャッシュキーと期限")
    key_args = {
        "model_id": LITE,
        "prompt_version": cost_lab.PROMPT_VERSION_COMPACT,
        "system": lean_system,
        "user_text": lean_blocks[0]["text"],
    }
    key = answer_cache.cache_key(**key_args)
    check("同じ条件なら同じキーになる", answer_cache.cache_key(**key_args) == key)
    check(
        "プロンプトの版が違えば別のキーになる",
        answer_cache.cache_key(**{**key_args, "prompt_version": "helpdesk-answer/v1-verbose"})
        != key,
    )
    check(
        "モデルが違えば別のキーになる",
        answer_cache.cache_key(**{**key_args, "model_id": MICRO}) != key,
    )
    answer_cache.clear(ddb)
    answer_cache.put(ddb, key, question="質問", answer=EXPECTED_ANSWER, output_tokens=66)
    check("保存した直後はヒットする", answer_cache.get(ddb, key) is not None)
    check(
        "期限を過ぎた項目はヒットにしない",
        answer_cache.get(ddb, key, now=time.time() + answer_cache.TTL_SECONDS + 1)
        is None,
    )
    check("clear で空になる", answer_cache.clear(ddb) >= 1 and answer_cache.count(ddb) == 0)

    # ------------------------------------------------------------------
    section("6. セマンティックキャッシュの誤ヒット")
    model_router.reset_mock()
    strict = answer_cache.SemanticCache(runtime, threshold=cost_lab.SEMANTIC_THRESHOLD)
    strict.put(poc_probe.QUESTIONS[0][0], EXPECTED_ANSWER)
    same = strict.lookup(poc_probe.QUESTIONS[0][0])
    danger = strict.lookup(cost_lab.DANGER_QUESTION)
    unrelated = strict.lookup(cost_lab.UNRELATED_QUESTION)
    paraphrase = strict.lookup(cost_lab.QUESTIONS["q-carryover-paraphrase"][0])
    check("同じ質問の類似度は 1.000000", usd(same["score"]) == "1.000000", same["score"])
    check("同じ質問はヒットする", same["hit"])
    check(
        "語が似ていて答えが違う質問は、無関係な質問より似ている",
        danger["score"] > unrelated["score"],
        (danger["score"], unrelated["score"]),
    )
    check(
        "しきい値 0.99 では誤ヒットしない",
        not danger["hit"] and danger["score"] < cost_lab.SEMANTIC_THRESHOLD,
        danger["score"],
    )
    check("しきい値 0.99 では言い換えも当たらない", not paraphrase["hit"], paraphrase["score"])
    loose = answer_cache.SemanticCache(runtime, threshold=danger["score"] - 0.01)
    loose.put(poc_probe.QUESTIONS[0][0], EXPECTED_ANSWER)
    loose_danger = loose.lookup(cost_lab.DANGER_QUESTION)
    check("しきい値を実測類似度の直下まで緩めると誤ヒットする", loose_danger["hit"],
          loose_danger["score"])
    check(
        "誤ヒットで返るのは別の質問の答え（繰越上限の答え）",
        loose_danger["entry"]["answer"] == EXPECTED_ANSWER
        and "付与" not in loose_danger["entry"]["answer"],
    )
    check(
        "完全一致で当たる件はセマンティックでも必ず当たる（呼び出し回数が等しい）",
        usage_e["perModel"][LITE]["calls"] == usage_d["perModel"][LITE]["calls"],
    )

    # ------------------------------------------------------------------
    section("7. 損益分岐の計算")
    for model_id, want in (
        (MICRO, "0.000077"),
        (LITE, "0.000132"),
        (PRO, "0.001760"),
        (HAIKU, "0.002000"),
        (SONNET, "0.007500"),
        (LLAMA, "0.000936"),
    ):
        check(
            f"{model_id} の参照ワークロード1回は {want} USD",
            usd(throughput.usd_per_request(model_id)) == want,
            throughput.usd_per_request(model_id),
        )
    check(
        "出力の重みは Nova 系 4倍 / Anthropic 系 5倍 / Meta 1倍",
        abs(throughput.output_token_weight(LITE) - 4.0) < 1e-9
        and abs(throughput.output_token_weight(SONNET) - 5.0) < 1e-9
        and abs(throughput.output_token_weight(LLAMA) - 1.0) < 1e-9,
        (
            throughput.output_token_weight(LITE),
            throughput.output_token_weight(SONNET),
            throughput.output_token_weight(LLAMA),
        ),
    )
    check(
        "入力の費用比率は Nova 45.5% / Anthropic 40.0% / Meta 76.9%",
        [
            round(throughput.input_cost_share(m), 3)
            for m in (LITE, SONNET, LLAMA)
        ]
        == [0.455, 0.4, 0.769],
        [round(throughput.input_cost_share(m), 3) for m in (LITE, SONNET, LLAMA)],
    )
    check(
        "20 USD/時の損益分岐は Nova Lite で 151,515 件/時",
        f"{throughput.break_even_requests_per_hour(LITE):,.0f}" == "151,515",
        throughput.break_even_requests_per_hour(LITE),
    )
    lite_verdict = throughput.provisioned_verdict(LITE)
    sonnet_verdict = throughput.provisioned_verdict(SONNET)
    check(
        "5,000件/時では Nova Lite の稼働率は 3.3% でオンデマンドが安い",
        round(lite_verdict["utilization"], 3) == 0.033
        and lite_verdict["cheaper"] == "on_demand",
        lite_verdict,
    )
    check(
        "同じ件数でも Claude Sonnet 4.5 は稼働率 187.5% で確約が安い",
        round(sonnet_verdict["utilization"], 3) == 1.875
        and sonnet_verdict["cheaper"] == "provisioned",
        sonnet_verdict,
    )
    check(
        "20,000件/日はオンデマンド 2.640 USD、バッチ 1.320 USD",
        f"{throughput.on_demand_usd(LITE):.3f}" == "2.640"
        and f"{throughput.batch_usd(LITE):.3f}" == "1.320",
        (throughput.on_demand_usd(LITE), throughput.batch_usd(LITE)),
    )
    check(
        "書き込み1.25倍・読み出し0.1倍なら2回目から得",
        throughput.cache_break_even_calls() == 2,
        throughput.cache_break_even_calls(),
    )
    check(
        "モックの会計（無料）なら1回目から得",
        throughput.cache_break_even_calls(0.0, 0.0) == 1,
    )
    check(
        "書き込み2.0倍・読み出し0.5倍なら3回目から得",
        throughput.cache_break_even_calls(2.0, 0.5) == 3,
        throughput.cache_break_even_calls(2.0, 0.5),
    )
    scenario = {
        "calls": 10,
        "prefix_tokens": 2_000,
        "variable_tokens": 200,
        "output_tokens": 300,
    }
    plain = throughput.cache_usd(LITE, cached=False, **scenario)
    cached = throughput.cache_usd(LITE, cached=True, **scenario)
    mocked = throughput.cache_usd(
        LITE, cached=True, write_multiplier=0.0, read_multiplier=0.0, **scenario
    )
    check(
        "接頭辞2,000を10回: 0.002040 -> 0.001098 USD（46.2% 減）",
        usd(plain) == "0.002040" and usd(cached) == "0.001098"
        and f"{1 - cached / plain:.1%}" == "46.2%",
        (plain, cached),
    )
    check(
        "同じ条件をモックの会計で計算すると 0.000840 USD（58.8% 減）",
        usd(mocked) == "0.000840" and f"{1 - mocked / plain:.1%}" == "58.8%",
        mocked,
    )

    # ------------------------------------------------------------------
    section("8. ティア分けをコストの観点で見る（セッション9の再利用）")
    router = model_router.ModelRouter()
    check(
        "Micro -> Pro のブレークイーブンは 95.6%",
        f"{cascade.break_even_rate():.1%}" == "95.6%",
        cascade.break_even_rate(),
    )
    check(
        "単価差は 22.9倍",
        f"{throughput.usd_per_request(PRO) / throughput.usd_per_request(MICRO):.1f}"
        == "22.9",
    )
    usage_cascade, decisions = cascade.measure(
        lambda: cascade.run_cascade(cascade.WORKLOAD, router)
    )
    usage_top, _ = cascade.measure(
        lambda: cascade.run_single_tier(
            cascade.WORKLOAD, cascade.TIER2, cascade.TIER2_MAX_TOKENS, router
        )
    )
    tier1_calls = usage_cascade["perModel"].get(cascade.TIER1, {}).get("calls", 0)
    escalated = [d for d in decisions if d["path"] == "tier1>tier2"]
    rate = len(escalated) / tier1_calls
    saved = 1 - usage_cascade["estimatedUsdTotal"] / usage_top["estimatedUsdTotal"]
    check("実測のエスカレーション率は 1/11 = 9.1%",
          f"{len(escalated)}/{tier1_calls}" == "1/11" and f"{rate:.1%}" == "9.1%",
          (len(escalated), tier1_calls))
    check("エスカレーション率がブレークイーブンを下回っている",
          rate < cascade.break_even_rate())
    check(f"カスケードの削減率が 60〜70%（実測 {saved:.1%}）", 0.60 <= saved <= 0.70, saved)
    check("カスケードは全件を上位モデルへ投げるより安い",
          usage_cascade["estimatedUsdTotal"] < usage_top["estimatedUsdTotal"])

    # ------------------------------------------------------------------
    section("9. 並列度で増えるのは費用ではない")
    model_router.reset_mock()
    model_router.set_behavior(throttle_next=2)
    cost_lab.call(runtime, lean_system, lean_blocks, max_tokens=120, cache=False)
    throttled = model_router.mock_usage()
    check("2回スロットリングされた", throttled["throttled"] == 2, throttled["throttled"])
    check("会計に載った呼び出しは1回だけ", throttled["calls"] == 1, throttled["calls"])
    check("費用は成功した1回ぶんだけ",
          usd(throttled["estimatedUsdTotal"]) == "0.000021",
          throttled["estimatedUsdTotal"])

    # 後続セッションのために状態を戻す
    model_router.reset_mock()
    answer_cache.clear(ddb)
    check("後片付けができている", model_router.mock_usage()["calls"] == 0)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション16の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
