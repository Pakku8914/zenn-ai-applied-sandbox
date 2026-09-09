#!/usr/bin/env python3
"""セッション9の検証。

「事前ゲートと受け入れ判定でルーティング先が決まること」
「カスケードが全件を上位モデルへ投げるより安いこと」
「カナリアがハッシュで決定的に振り分けられ、1操作で戻せること」
「非同期の受け口（SQS）でも判断が変わらないこと」を確認します。
**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session09/verify.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, "/workspace/src/session02")
sys.path.insert(0, "/workspace/src/session09")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import batch_intake  # noqa: E402
import cascade  # noqa: E402
import model_router  # noqa: E402
import poc_probe  # noqa: E402
import release  # noqa: E402

FAILURES: list[str] = []

MICRO = "amazon.nova-micro-v1:0"
LITE = "amazon.nova-lite-v1:0"
PRO = "amazon.nova-pro-v1:0"
HAIKU = "anthropic.claude-3-5-haiku-20241022-v1:0"
SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
EMBED = "amazon.titan-embed-text-v2:0"

# 事前ゲートで上位モデルへ直行する件・呼んでから昇格する件（決定的）。
# req-012 は昇格しても上位で受け入れられない（渡した資料に答えの記述が無い）ため、
# 「昇格した集合」と「受け入れられなかった集合」がどちらも req-012 になる。
GATED = ["req-011"]
ESCALATED = ["req-012"]


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
    router = model_router.ModelRouter()

    # ------------------------------------------------------------------
    section("1. 単価差とブレークイーブンのエスカレーション率")
    c1 = catalog.cost_usd(MICRO, *cascade.REFERENCE_WORKLOAD)
    c2 = catalog.cost_usd(PRO, *cascade.REFERENCE_WORKLOAD)
    check("tier1 の参照ワークロード単価は 0.000077 USD", f"{c1:.6f}" == "0.000077", c1)
    check("tier2 の参照ワークロード単価は 0.001760 USD", f"{c2:.6f}" == "0.001760", c2)
    check(
        "Micro → Pro のブレークイーブンは 95.625%",
        abs(cascade.break_even_rate(MICRO, PRO) - 0.95625) < 1e-6,
        cascade.break_even_rate(MICRO, PRO),
    )
    check(
        "Haiku → Sonnet のブレークイーブンは 73.3%",
        round(cascade.break_even_rate(HAIKU, SONNET), 3) == 0.733,
        cascade.break_even_rate(HAIKU, SONNET),
    )
    check(
        "Lite → Pro のブレークイーブンは 92.5%",
        abs(cascade.break_even_rate(LITE, PRO) - 0.925) < 1e-6,
        cascade.break_even_rate(LITE, PRO),
    )
    check(
        "単価差が小さい組み合わせほどブレークイーブンは下がる",
        cascade.break_even_rate(HAIKU, SONNET) < cascade.break_even_rate(MICRO, PRO),
    )

    # ------------------------------------------------------------------
    section("2. 呼ぶ前に決める（事前ゲート）")
    check(
        "入力トークンの見積もりが API の実測値と一致する（資料つきの質問）",
        cascade.token_estimate(
            poc_probe.SYSTEM_PROMPT + cascade.prompt_text(cascade.WORKLOAD[5])
        )
        == cascade.call(
            cascade.WORKLOAD[5], MICRO, cascade.TIER1_MAX_TOKENS, router
        )["inputTokens"],
    )
    check(
        "入力トークンの見積もりが API の実測値と一致する（分類タスク）",
        cascade.token_estimate(
            poc_probe.SYSTEM_PROMPT + cascade.prompt_text(cascade.WORKLOAD[0])
        )
        == cascade.call(
            cascade.WORKLOAD[0], MICRO, cascade.TIER1_MAX_TOKENS, router
        )["inputTokens"],
    )
    gated = [r["requestId"] for r in cascade.WORKLOAD if cascade.pre_route(r)[0] == "tier2"]
    check("事前ゲートで直行するのは長い資料の1件だけ", gated == GATED, gated)
    check(
        "直行の理由は入力が長いこと",
        cascade.pre_route(cascade.WORKLOAD[10])[1] == "input_too_long",
        cascade.pre_route(cascade.WORKLOAD[10]),
    )
    check(
        "tier1 に任せていないタスクも呼ぶ前に弾く",
        cascade.pre_route({"task": "plan", "question": "移行計画を立ててください。"})
        == ("tier2", "task_out_of_scope"),
    )
    check(
        "tier1 の担当タスクは分類と資料つき応答の2つ",
        cascade.TIER1_TASKS == frozenset({"classify", "answer"}),
        cascade.TIER1_TASKS,
    )

    # ------------------------------------------------------------------
    section("3. 呼んだ後に決める（受け入れ判定）とルーティング結果")
    usage_cascade, decisions = cascade.measure(
        lambda: cascade.run_cascade(cascade.WORKLOAD, router)
    )
    by_id = {d["requestId"]: d for d in decisions}
    check("12件すべてに判断が付いている", len(decisions) == 12, len(decisions))
    check(
        "受け入れられなかったのは req-012 の1件だけ",
        [d["requestId"] for d in decisions if d["outcome"] != "accepted"] == ESCALATED,
        [d["requestId"] for d in decisions if d["outcome"] != "accepted"],
    )
    check(
        "事前ゲートで上位へ直行した集合",
        [d["requestId"] for d in decisions if d["path"] == "gate>tier2"] == GATED,
    )
    check(
        "呼んでから上位へ昇格した集合",
        [d["requestId"] for d in decisions if d["path"] == "tier1>tier2"] == ESCALATED,
    )
    check(
        "昇格の理由は根拠を提示できなかったこと",
        by_id["req-012"]["reason"] == "not_grounded",
        by_id["req-012"]["reason"],
    )
    check(
        "req-012 は上位でも受け入れられず exhausted になる",
        by_id["req-012"]["outcome"] == "exhausted"
        and by_id["req-012"]["servedBy"] is None,
        (by_id["req-012"]["outcome"], by_id["req-012"]["servedBy"]),
    )
    check(
        "昇格しても救えない件には縮退の定型文を返す",
        by_id["req-012"]["text"] == model_router.DEFAULT_CONFIG["degradedMessage"],
    )
    check(
        "この12件では打ち切りによる昇格は起きていない",
        all(d["reason"] != "truncated" for d in decisions),
        [d["requestId"] for d in decisions if d["reason"] == "truncated"],
    )
    check(
        "残り10件は小型モデルで完結している",
        len([d for d in decisions if d["path"] == "tier1"]) == 10,
    )
    check(
        "分類タスクの受け入れは許可ラベルの集合で判定している",
        all(by_id[f"req-{i:03d}"]["reason"] == "label_ok" for i in range(1, 6)),
    )
    check(
        "資料つき応答の受け入れは根拠提示で判定している",
        all(
            by_id[f"req-{i:03d}"]["reason"] == "grounded"
            for i in (6, 7, 8, 9, 10)
        ),
    )
    tier1_calls = usage_cascade["perModel"].get(MICRO, {}).get("calls", 0)
    tier2_calls = usage_cascade["perModel"].get(PRO, {}).get("calls", 0)
    check("小型モデルの呼び出しは11回", tier1_calls == 11, tier1_calls)
    check("上位モデルの呼び出しは2回", tier2_calls == 2, tier2_calls)
    check("呼び出し総数は13回（昇格した1件は二重に払う）",
          usage_cascade["calls"] == 13, usage_cascade["calls"])
    escalation_rate = len(ESCALATED) / tier1_calls
    check(
        "エスカレーション率がブレークイーブンを下回っている",
        escalation_rate < cascade.break_even_rate(),
        (round(escalation_rate, 3), round(cascade.break_even_rate(), 3)),
    )

    # ------------------------------------------------------------------
    section("4. コスト（GET /_mock/usage の estimatedUsd）")
    usage_top, _ = cascade.measure(
        lambda: cascade.run_single_tier(
            cascade.WORKLOAD, PRO, cascade.TIER2_MAX_TOKENS, router
        )
    )
    usage_floor, _ = cascade.measure(
        lambda: cascade.run_single_tier(
            cascade.WORKLOAD, MICRO, cascade.TIER1_MAX_TOKENS, router
        )
    )
    base = usage_top["estimatedUsdTotal"]
    cascade_usd = usage_cascade["estimatedUsdTotal"]
    floor_usd = usage_floor["estimatedUsdTotal"]
    saved = 1 - cascade_usd / base
    index_cascade = cascade_usd / base * 100
    index_floor = floor_usd / base * 100
    check("基準（全件を上位モデル）は12回の呼び出し", usage_top["calls"] == 12)
    check("基準では上位モデルだけが会計に載る",
          list(usage_top["perModel"]) == [PRO], list(usage_top["perModel"]))
    check("カスケードは2モデルが会計に載る",
          sorted(usage_cascade["perModel"]) == sorted([MICRO, PRO]),
          sorted(usage_cascade["perModel"]))
    check("カスケードは全件を上位モデルへ投げるより安い", cascade_usd < base,
          (cascade_usd, base))
    check("カスケードは全件を小型モデルへ投げるより高い", cascade_usd > floor_usd,
          (cascade_usd, floor_usd))
    check(f"削減率が 35% 以上（実測 {saved:.1%}）", saved >= 0.35, saved)
    check(f"削減率が 85% 未満（実測 {saved:.1%}）", saved < 0.85, saved)
    check(f"カスケード指数が 25〜70（実測 {index_cascade:.0f}）",
          25 <= index_cascade <= 70, index_cascade)
    check(f"小型のみの指数が 1〜15（実測 {index_floor:.0f}）",
          1 <= index_floor <= 15, index_floor)

    # ------------------------------------------------------------------
    section("5. モデルを上げても直らないケースは縮退する")
    orphan = {
        "requestId": "req-901",
        "task": "answer",
        "question": "退職金の計算方法を教えてください。",
        "context": "経費精算の締め日は毎月10日です。",
    }
    usage_orphan, exhausted = cascade.measure(
        lambda: cascade.run_one(orphan, router)
    )
    check("経路は tier1 → tier2", exhausted["path"] == "tier1>tier2", exhausted["path"])
    check("結果は exhausted", exhausted["outcome"] == "exhausted", exhausted["outcome"])
    check("どの層も答えていない", exhausted["servedBy"] is None)
    check("2回ぶんの料金を払っている", usage_orphan["calls"] == 2, usage_orphan["calls"])
    check(
        "利用者には縮退の定型文を返す",
        exhausted["text"] == model_router.DEFAULT_CONFIG["degradedMessage"],
    )

    # ------------------------------------------------------------------
    # 本章のワークロードでは打ち切りが起きないため、モックの制御 API で確実に起こして
    # 「打ち切られた応答は受け入れない」という判定順序だけを単独で確かめる。
    # 他の計測に影響しないよう、実験の前後で必ず状態を初期化する。
    section("5-2. 打ち切られた応答は受け入れない（force_max_tokens）")
    model_router.reset_mock()
    model_router.set_behavior(force_max_tokens=True)
    truncated = cascade.run_one(cascade.WORKLOAD[5], router)
    check(
        "打ち切りは受け入れ判定で先に弾かれる",
        truncated["reason"] == "truncated",
        truncated["reason"],
    )
    check("小型層から上位層へ昇格する", truncated["path"] == "tier1>tier2", truncated["path"])
    check(
        "上位層でも打ち切られれば exhausted",
        truncated["outcome"] == "exhausted",
        truncated["outcome"],
    )
    model_router.reset_mock()
    check(
        "実験の後にモックの状態を戻している",
        model_router.mock_usage()["calls"] == 0,
        model_router.mock_usage()["calls"],
    )

    # ------------------------------------------------------------------
    section("6. カナリアは乱数ではなくハッシュで決める")
    base_release = release.bootstrap()
    ids = release.synthetic_ids(1_000)
    at_10 = {**base_release, "canaryPercent": 10}
    at_25 = {**base_release, "canaryPercent": 25}
    check("既定はカナリア 0%", base_release["canaryPercent"] == 0)
    check(
        "同じ識別子は何度評価しても同じ側になる",
        len({release.choose_arm(ids[0], at_10) for _ in range(100)}) == 1,
    )
    check(
        "バケットは 0〜99 に収まる",
        all(0 <= release.bucket_of(r, at_10["salt"]) < 100 for r in ids[:50]),
    )
    ten = set(release.canary_ids(ids, at_10))
    twenty_five = set(release.canary_ids(ids, at_25))
    check("10% のカナリア集合は 25% に含まれる（並び替えが起きない）",
          ten <= twenty_five, len(ten - twenty_five))
    check("0% なら全件が安定版",
          release.distribution(ids, {**base_release, "canaryPercent": 0})["canary"] == 0)
    check("100% なら全件がカナリア",
          release.distribution(ids, {**base_release, "canaryPercent": 100})["stable"] == 0)
    check(
        "salt を変えると割り当てが入れ替わる",
        set(release.canary_ids(ids, {**at_10, "salt": "helpdesk-other"})) != ten,
    )
    ratio = len(ten) / len(ids)
    check(f"1,000件の実測比率が 6〜14%（実測 {ratio:.1%}）", 0.06 <= ratio <= 0.14, ratio)
    check(
        "0% のときはハッシュを評価せずに安定版へ返す",
        release.choose_arm("hd-00000", {**base_release, "canaryPercent": 0}) == "stable",
    )

    # ------------------------------------------------------------------
    section("7. 壊れたリリース設定を配らない")
    check(
        "カタログに無いモデル ID を弾く",
        raises_value_error(
            lambda: release.validate_release({**base_release, "canary": "openai.gpt-5"})
        ),
    )
    check(
        "Converse 非対応（埋め込み）のモデルを弾く",
        raises_value_error(
            lambda: release.validate_release({**base_release, "canary": EMBED})
        ),
    )
    check(
        "stable と canary が同じ設定を弾く",
        raises_value_error(
            lambda: release.validate_release(
                {**base_release, "canary": base_release["stable"]}
            )
        ),
    )
    check(
        "割合が範囲外の設定を弾く",
        raises_value_error(
            lambda: release.validate_release({**base_release, "canaryPercent": 120})
        ),
    )
    check(
        "salt が空の設定を弾く",
        raises_value_error(
            lambda: release.validate_release({**base_release, "salt": ""})
        ),
    )

    # ------------------------------------------------------------------
    section("8. カナリア側の障害と、1操作のロールバック")
    model_router.reset_mock()
    live = release.set_canary_percent(25)
    check("段階を進めた割合が読み直せる",
          release.load_release()["canaryPercent"] == 25)
    check("どこから来たかが残る", live["previousPercent"] == 0, live["previousPercent"])
    hit = release.canary_ids(ids, live)[0]
    miss = next(r for r in ids if release.choose_arm(r, live) == "stable")
    question, source = poc_probe.QUESTIONS[0]
    model_router.set_behavior(unavailable_model=live["canary"])
    fresh = model_router.ModelRouter()
    served = release.serve(hit, question, source, live, fresh)
    check("カナリアに割り当てられている", served["arm"] == "canary", served["arm"])
    check("実際に答えたのは安定版", served["modelId"] == live["stable"], served["modelId"])
    check("serviceLevel は fallback", served["serviceLevel"] == "fallback")
    check(
        "1回目の試行はカナリア側の 503",
        served["attempts"][0]
        == {"modelId": live["canary"], "outcome": "ServiceUnavailableException"},
        served["attempts"],
    )
    untouched = release.serve(miss, question, source, live, model_router.ModelRouter())
    check("安定版に当たった側は影響を受けない",
          untouched["arm"] == "stable" and untouched["serviceLevel"] == "full",
          (untouched["arm"], untouched["serviceLevel"]))
    model_router.set_behavior(unavailable_model=None)

    rolled = release.rollback()
    after = release.load_release()
    check("ロールバックで割合が 0 になる", after["canaryPercent"] == 0, after)
    check("どこから戻したかが残る", rolled["rolledBackFrom"] == 25, rolled)
    check("直後の全件が安定版へ戻る",
          release.distribution(ids, after)["canary"] == 0)

    # ------------------------------------------------------------------
    section("9. 非同期の受け口（SQS）でも判断は変わらない")
    model_router.reset_mock()
    sqs = clients.aws("sqs")
    url = batch_intake.queue_url(sqs)
    batch_intake.clear(sqs, url)
    sent = batch_intake.enqueue(sqs, url, cascade.WORKLOAD)
    check("12件を投入できた", sent == 12, sent)
    done = batch_intake.drain(sqs, url, router, expected=sent)
    check("12件すべて処理した", len(done) == 12, len(done))
    check(
        "処理した識別子の集合が一致する",
        {d["requestId"] for d in done}
        == {r["requestId"] for r in cascade.WORKLOAD},
    )
    check(
        "経路の内訳は同期実行と同じ",
        sorted(d["path"] for d in done) == sorted(d["path"] for d in decisions),
    )
    left = sqs.receive_message(
        QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=1
    ).get("Messages", [])
    check("キューが空になった", not left, left)

    # 後続セッションのために状態を戻す
    model_router.reset_mock()
    release.bootstrap()

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション9の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
