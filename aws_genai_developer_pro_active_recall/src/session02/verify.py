#!/usr/bin/env python3
"""セッション2の検証。

「選定表がカタログの実データから作られていること」「設定だけでモデルが差し替わること」
「障害時に切り替わり、切り替え先も無ければ縮退すること」を確認します。
**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session02/verify.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")

from botocore.exceptions import ClientError  # noqa: E402

from bedrock_mock import catalog  # noqa: E402

import model_matrix  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402

FAILURES: list[str] = []

MICRO = "amazon.nova-micro-v1:0"
LITE = "amazon.nova-lite-v1:0"
PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
LLAMA = "meta.llama3-3-70b-instruct-v1:0"
EMBED = "amazon.titan-embed-text-v2:0"

# 参照ワークロード（入力1,000 / 出力300 トークン）で並べたときのコスト順
COST_ORDER = [MICRO, LITE, LLAMA, PRO, HAIKU, SONNET]

# 前章と同じ質問・同じ system プロンプトなので、計測値も前章と一致する
EXPECTED_TOKENS = (90, 66)
EXPECTED_LATENCY_MS = 86


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
    # 前セッションの障害注入設定が残っていると落ちるため、必ず最初にリセットする
    model_router.reset_mock()

    question, source = poc_probe.QUESTIONS[0]

    # ------------------------------------------------------------------
    section("1. 選定表はカタログの実データから作られている")
    check("カタログのモデルは7件", len(catalog.MODELS) == 7, len(catalog.MODELS))
    ids = [spec.model_id for spec in model_matrix.conversational()]
    check("会話に使える候補は6件（埋め込みを除く）", len(ids) == 6, ids)
    check("埋め込み専用モデルは候補に入らない", EMBED not in ids, ids)
    check(
        "参照ワークロードのコスト順が決定的",
        [row["modelId"] for row in model_matrix.rows()] == COST_ORDER,
        [row["modelId"] for row in model_matrix.rows()],
    )
    for model_id, expected in (
        (MICRO, "0.000077"),
        (LITE, "0.000132"),
        (LLAMA, "0.000936"),
        (PRO, "0.001760"),
        (HAIKU, "0.002000"),
        (SONNET, "0.007500"),
    ):
        actual = f"{model_matrix.call_cost_usd(model_id):.6f}"
        check(f"{model_id} の1回あたり推定コストが {expected} USD", actual == expected, actual)

    # ------------------------------------------------------------------
    section("2. 要件で絞ってから値段で並べる")
    check(
        "テキストのみ・128,000以上 → 最安は Nova Micro",
        model_matrix.cheapest(modality=("TEXT",), min_context_window=128_000) == MICRO,
    )
    check(
        "画像入力が必要 → 最安は Nova Lite",
        model_matrix.cheapest(modality=("IMAGE",)) == LITE,
    )
    check(
        "画像入力が必要 → 候補は4件（テキスト専用が落ちる）",
        len(model_matrix.select(modality=("IMAGE",))) == 4,
        model_matrix.select(modality=("IMAGE",)),
    )
    check(
        "ツール利用＋レイテンシ最適化＋200,000以上 → Nova Lite",
        model_matrix.cheapest(
            modality=("TEXT",),
            min_context_window=200_000,
            needs_tool_use=True,
            needs_optimized_latency=True,
        )
        == LITE,
    )
    check(
        "出力32,000トークン以上が必要 → Claude Sonnet 4.5 だけ",
        model_matrix.select(min_output_tokens=32_000) == [SONNET],
        model_matrix.select(min_output_tokens=32_000),
    )
    check(
        "コンテキスト長 500,000 以上 → 候補なし",
        model_matrix.select(min_context_window=500_000) == [],
    )
    balanced = model_matrix.call_cost_usd(HAIKU) / model_matrix.call_cost_usd(LLAMA)
    heavy = model_matrix.call_cost_usd(
        HAIKU, model_matrix.OUTPUT_HEAVY_WORKLOAD
    ) / model_matrix.call_cost_usd(LLAMA, model_matrix.OUTPUT_HEAVY_WORKLOAD)
    check(
        "出力が長い用途では入出力同単価のモデルが相対的に有利になる",
        heavy > balanced * 2,
        (round(balanced, 3), round(heavy, 3)),
    )

    # ------------------------------------------------------------------
    section("3. 設定レイヤ（AppConfig 相当・SSM パラメータストア）")
    config = model_router.bootstrap()
    check("既定の primary は Nova Lite", config["primary"] == LITE, config["primary"])
    check(
        "代替先が1つ以上定義されている",
        config["fallbacks"] == [HAIKU],
        config["fallbacks"],
    )
    swapped = {**model_router.DEFAULT_CONFIG, "primary": HAIKU}
    model_router.put_config(swapped)
    check(
        "配布した設定がそのまま読める（コードは変えていない）",
        model_router.load_config(force=True, now=1000.0)["primary"] == HAIKU,
    )
    model_router.put_config(model_router.DEFAULT_CONFIG)
    check(
        "TTL 内（+10秒）は読み直さない",
        model_router.load_config(now=1010.0)["primary"] == HAIKU,
    )
    check(
        "TTL 経過後（+40秒）は新しい設定を読む",
        model_router.load_config(now=1040.0)["primary"] == LITE,
    )

    # ------------------------------------------------------------------
    section("4. 壊れた設定を配らない・読み込みでも落ちない")
    check(
        "カタログに無いモデル ID を弾く",
        raises_value_error(
            lambda: model_router.validate_config(
                {**model_router.DEFAULT_CONFIG, "primary": "openai.gpt-5"}
            )
        ),
    )
    check(
        "Converse 非対応（埋め込み）のモデルを弾く",
        raises_value_error(
            lambda: model_router.validate_config(
                {**model_router.DEFAULT_CONFIG, "primary": EMBED}
            )
        ),
    )
    check(
        "未知の地理接頭辞を弾く",
        raises_value_error(
            lambda: model_router.validate_config(
                {**model_router.DEFAULT_CONFIG, "geoPrefix": "jp-east."}
            )
        ),
    )
    check(
        "縮退時の応答文が空の設定を弾く",
        raises_value_error(
            lambda: model_router.validate_config(
                {**model_router.DEFAULT_CONFIG, "degradedMessage": ""}
            )
        ),
    )
    check(
        "配布時にも検証が走る（壊れた設定はデプロイできない）",
        raises_value_error(
            lambda: model_router.put_config(
                {**model_router.DEFAULT_CONFIG, "primary": "openai.gpt-5"}
            )
        ),
    )
    # 手作業で壊された設定が届いた状況の再現
    model_router.put_config(
        {**model_router.DEFAULT_CONFIG, "primary": "openai.gpt-5"}, validate=False
    )
    check(
        "壊れた設定が届いても直前の正しい設定を使い続ける",
        model_router.load_config(force=True, now=2000.0)["primary"] == LITE,
    )
    check(
        "設定の問題は監視へ出せる形で記録される",
        model_router.LAST_CONFIG_ERROR is not None,
        model_router.LAST_CONFIG_ERROR,
    )
    model_router.put_config({**model_router.DEFAULT_CONFIG, "primary": HAIKU})
    check(
        "設定が直れば次の読み込みで反映される",
        model_router.load_config(force=True, now=2100.0)["primary"] == HAIKU
        and model_router.LAST_CONFIG_ERROR is None,
    )

    # ------------------------------------------------------------------
    section("5. サーキットブレーカーの状態遷移")
    clock = {"t": 0.0}
    breaker = model_router.CircuitBreaker(
        failure_threshold=2, cooldown_seconds=30.0, time_fn=lambda: clock["t"]
    )
    check("初期状態は CLOSED", breaker.state == "CLOSED")
    breaker.on_failure()
    check("1回の失敗では開かない", breaker.state == "CLOSED", breaker.failures)
    breaker.on_failure()
    check("閾値に達すると OPEN", breaker.state == "OPEN", breaker.failures)
    check("OPEN の間は呼ばない", breaker.allow() is False)
    clock["t"] = 31.0
    check("クールダウン経過で1回だけ試す（HALF_OPEN）", breaker.allow() is True)
    check("状態は HALF_OPEN", breaker.state == "HALF_OPEN", breaker.state)
    breaker.on_failure()
    check("半開で失敗したら即 OPEN に戻る", breaker.state == "OPEN")
    check("戻った直後は呼ばない", breaker.allow() is False)
    clock["t"] = 70.0
    breaker.allow()
    breaker.on_success()
    check(
        "半開で成功したら CLOSED に戻り失敗カウンタも消える",
        breaker.state == "CLOSED" and breaker.failures == 0,
        (breaker.state, breaker.failures),
    )
    check(
        "切り替えても直らないエラーだけを FATAL 扱いにしている",
        "ValidationException" in model_router.FATAL_CODES
        and "ServiceUnavailableException" not in model_router.FATAL_CODES,
        sorted(model_router.FATAL_CODES),
    )

    # ------------------------------------------------------------------
    section("6. 通常時の呼び出しと推論プロファイル")
    model_router.reset_mock()
    router = model_router.ModelRouter(config=model_router.DEFAULT_CONFIG)
    normal = router.invoke(question, context=source)
    check("primary で応答する", normal["modelId"] == LITE, normal["modelId"])
    check("serviceLevel は full", normal["serviceLevel"] == "full")
    check("根拠を提示している", normal["grounded"] is True, normal["text"][:40])
    check(
        "計測値は前章と一致する（入力90 / 出力66 トークン）",
        (normal["inputTokens"], normal["outputTokens"]) == EXPECTED_TOKENS,
        (normal["inputTokens"], normal["outputTokens"]),
    )
    check(
        "レイテンシは 20 + 出力トークン",
        normal["latencyMs"] == EXPECTED_LATENCY_MS == 20 + normal["outputTokens"],
        normal["latencyMs"],
    )
    check(
        "Nova Lite の推定コストは 0.000021 USD",
        f"{normal['estimatedUsd']:.6f}" == "0.000021",
        normal["estimatedUsd"],
    )
    check("地理接頭辞なしの呼び出しは geo が '-'", normal["geo"] == "-", normal["geo"])

    via_profile = router.invoke(
        question,
        context=source,
        config={**model_router.DEFAULT_CONFIG, "geoPrefix": "us."},
    )
    check(
        "推論プロファイル ID で呼べる",
        via_profile["modelId"] == f"us.{LITE}",
        via_profile["modelId"],
    )
    check("解決先のモデルは同じ", via_profile["baseModelId"] == LITE)
    check("解決された地理が返る", via_profile["geo"] == "us", via_profile["geo"])
    check(
        "出力テキストとトークン数は接頭辞なしと一致する",
        via_profile["text"] == normal["text"]
        and via_profile["outputTokens"] == normal["outputTokens"],
    )

    # ------------------------------------------------------------------
    section("7. 障害時のフェイルオーバーと会計")
    model_router.reset_mock()
    model_router.set_behavior(unavailable_model=LITE)
    router = model_router.ModelRouter(config=model_router.DEFAULT_CONFIG)
    failed_over = router.invoke(question, context=source)
    check("代替モデルで応答する", failed_over["modelId"] == HAIKU, failed_over["modelId"])
    check("serviceLevel は fallback", failed_over["serviceLevel"] == "fallback")
    check(
        "1回目の試行は ServiceUnavailableException",
        failed_over["attempts"][0]
        == {"modelId": LITE, "outcome": "ServiceUnavailableException"},
        failed_over["attempts"],
    )
    check(
        "回答の質は落ちていない（同じ根拠・同じ出力トークン）",
        failed_over["grounded"] is True
        and failed_over["outputTokens"] == EXPECTED_TOKENS[1],
    )
    check(
        "代替先の推定コストは 0.000336 USD（16倍）",
        f"{failed_over['estimatedUsd']:.6f}" == "0.000336"
        and round(failed_over["estimatedUsd"] / normal["estimatedUsd"]) == 16,
        failed_over["estimatedUsd"],
    )
    usage = model_router.mock_usage()
    check("成功した呼び出しだけが会計に載る", usage["calls"] == 1, usage["calls"])
    check(
        "落ちたモデルのトークンは計上されない",
        list(usage["perModel"]) == [HAIKU],
        list(usage["perModel"]),
    )

    router.invoke(question, context=source)
    check(
        "連続失敗でブレーカーが開く",
        router.breaker(LITE).state == "OPEN",
        router.breaker(LITE).state,
    )
    skipped = router.invoke(question, context=source)
    check(
        "開いている間は呼ばずに次の候補へ回す",
        skipped["attempts"][0] == {"modelId": LITE, "outcome": "skipped_open"},
        skipped["attempts"],
    )
    check("それでも応答は返る", skipped["serviceLevel"] == "fallback")
    profile_call = router.invoke(
        question,
        context=source,
        config={**model_router.DEFAULT_CONFIG, "geoPrefix": "us."},
    )
    check(
        "推論プロファイル経由は別の呼び出し経路として扱われる",
        profile_call["serviceLevel"] == "full" and profile_call["geo"] == "us",
        (profile_call["serviceLevel"], profile_call["geo"]),
    )

    # ------------------------------------------------------------------
    section("8. 切り替えても直らないエラーは切り替えない")
    model_router.reset_mock()
    model_router.set_behavior(force_validation_error=True)
    strict = model_router.ModelRouter(config=model_router.DEFAULT_CONFIG)
    raised = ""
    try:
        strict.invoke(question, context=source)
    except ClientError as exc:
        raised = exc.response["Error"]["Code"]
    check("ValidationException はそのまま呼び出し元へ返る", raised == "ValidationException", raised)
    check(
        "代替モデルを試していない（1回で止まる）",
        len(strict.last_attempts) == 1,
        strict.last_attempts,
    )
    check(
        "ブレーカーは開かない（相手の障害ではないため）",
        strict.breaker(LITE).state == "CLOSED",
        strict.breaker(LITE).state,
    )
    model_router.set_behavior(force_validation_error=False)

    # ------------------------------------------------------------------
    section("9. 代替先が無いときの段階的縮退")
    model_router.reset_mock()
    model_router.set_behavior(unavailable_model=LITE)
    lonely = model_router.ModelRouter(
        config={**model_router.DEFAULT_CONFIG, "fallbacks": []}
    )
    degraded = lonely.invoke(question, context=source)
    check("serviceLevel は degraded", degraded["serviceLevel"] == "degraded")
    check("モデルは使われていない", degraded["modelId"] is None)
    check(
        "定型文で答える（作り話をしない）",
        degraded["text"] == model_router.DEFAULT_CONFIG["degradedMessage"],
        degraded["text"],
    )
    check("根拠提示は False（できないことをできると言わない）", degraded["grounded"] is False)
    check(
        "縮退でも例外は投げない（入口の API は応答を返せる）",
        degraded["attempts"][0]["outcome"] == "ServiceUnavailableException",
        degraded["attempts"],
    )

    # 後続セッションのために状態を戻す
    model_router.reset_mock()
    model_router.put_config(model_router.DEFAULT_CONFIG)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション2の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
