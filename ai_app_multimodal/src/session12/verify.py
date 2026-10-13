"""セッション12の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session12

合否は件数・指標・CER の上限・回数で決める。処理時間は合否に使わない（表示もしない）。
Whisper は small（キャッシュ済み）・int8・beam 1 だけを使う。
"""

from __future__ import annotations

import asyncio
import random

import httpx2
import numpy as np

from kondate.metrics import normalize_ja
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session12 import eval_cer, eval_latency
from src.session12.eval_cer import SENTENCES, aggregate
from src.session12.eval_extract import ERROR_FRIDGE, ERROR_RECEIPT, error_cases, mock_cases, run_cases
from src.session12.eval_latency import percentile, summarize as latency_summary
from src.session12.evaluate import build_report, find_regressions, latency_notes
from src.session12.gold import check_media, fridge_gold, receipt_gold
from src.session12.matching import FIELD_RULES, amount_ok, norm_name, score_case, summarize

MOCK = get_settings().mockllm_url


async def mock(method: str, path: str) -> dict:
    async with httpx2.AsyncClient(base_url=MOCK, timeout=10) as c:
        r = await c.request(method, path)
        r.raise_for_status()
        return r.json()


def counts(score) -> tuple:
    return (score.predicted, score.gold, score.matched, score.fields_correct, score.fields_checked, score.exact)


@check("V1 正解データは make_media.py の元データから作り、画像・PDF の版も一致する")
def _():
    eq([(i["name"], i["amount"]) for i in fridge_gold().items],
       [("キャベツ", None), ("鶏むね肉", 1), ("卵", 4), ("にんじん", 1), ("牛乳", 1)], "冷蔵庫の正解")
    g = receipt_gold("receipt.pdf")
    eq(g.header, {"store": "こんだてマート", "purchased_at": "2026-10-01", "total": 1072}, "レシート全体")
    eq([(i["name"], i["quantity"], i["price"]) for i in g.items],
       [("鶏むね肉", 1, 398), ("キャベツ", 1, 198), ("卵（10個入り）", 1, 248), ("牛乳", 1, 228)], "レシートの品目")
    check_media(["fridge.jpg", "receipt.png", "receipt.pdf"])
    return "冷蔵庫 5件（キャベツの数量は採点しない）・レシート 4件・合計 1072円"


@check("V2 照合の規則：名前は表記ゆれをそろえて比べ、数量は 10% まで、日付は形も含めてぴったり")
def _():
    eq(norm_name("鶏ムネ肉"), norm_name("鶏むね肉"), "カタカナとひらがな")
    eq(norm_name("卵 (10個入り)"), norm_name("卵（10個入り）"), "括弧と空白")
    eq(norm_name("人参"), norm_name("にんじん"), "表記ゆれ")
    eq([amount_ok(4, 4), amount_ok(3, 4), amount_ok(105, 100), amount_ok(0.5, 1)], [True, False, True, False], "数量")
    eq([FIELD_RULES["purchased_at"]("2026/10/01", "2026-10-01"), FIELD_RULES["price"](223, 228)], [False, False],
       "日付の形・金額")
    return "鶏ムネ肉＝鶏むね肉・人参＝にんじん・卵 4≠3・105≒100・2026/10/01≠2026-10-01"


@check("V3 誤りを手で作って採点する（LLM なし）：余計・見逃し・数量違い・金額違いを数える")
def _():
    pred = {"items": [{"name": i["name"], "amount": i["amount"]} for i in ERROR_FRIDGE["ingredients"]], "header": {}}
    s = score_case("fridge", fridge_gold(), pred)
    eq(counts(s), (5, 5, 4, 2, 3, False), "冷蔵庫（予測・正解・一致・項目○・項目数・完全一致）")
    eq(s.errors, ("卵 の amount：3 ≠ 4", "余計：ズッキーニ", "見逃し：牛乳"), "冷蔵庫の誤り")
    header = {k: ERROR_RECEIPT[k] for k in ("store", "purchased_at", "total")}
    r = score_case("receipt", receipt_gold("receipt.png"), {"items": ERROR_RECEIPT["items"], "header": header})
    eq(counts(r), (4, 4, 4, 10, 11, False), "レシート")
    eq(r.errors, ("牛乳 の price：223 ≠ 228",), "レシートの誤り")
    dup = score_case("dup", fridge_gold(), {"items": [{"name": "卵", "amount": 4}] * 2, "header": {}})
    eq((dup.matched, dup.errors[0]), (1, "余計：卵"), "同じ名前の2件目")
    return "冷蔵庫 一致4/5・項目2/3／レシート 一致4/4・項目10/11／同じ名前の2件目は余計"


@check("V4 mockllm の3件をパイプラインに通すと、すべて一致する（＝パイプラインの回帰テスト）")
async def _():
    await mock("POST", "/_mock/reset")
    results = await run_cases(mock_cases())
    eq([counts(s) for s, _ in results],
       [(5, 5, 5, 4, 4, True), (4, 4, 4, 11, 11, True), (4, 4, 4, 11, 11, True)], "ケースごと")
    eq([issues for _, issues in results], [[], [], []], "要確認")
    eq(summarize(s for s, _ in results),
       {"cases": 3, "precision": 1.0, "recall": 1.0, "field_accuracy": 1.0, "exact_match_rate": 1.0}, "合計")
    eq((await mock("GET", "/_mock/stats"))["by_scenario"], {"fridge_photo": 1, "receipt": 2}, "mockllm のシナリオと回数")
    return "3件とも完全一致・適合率 1.0・再現率 1.0／fridge_photo 1回・receipt 2回"


@check("V5 誤りを含む応答を混ぜると指標が下がり、要確認が拾う誤りと拾わない誤りに分かれる")
async def _():
    results = await run_cases(mock_cases() + error_cases())
    eq(summarize(s for s, _ in results),
       {"cases": 5, "precision": 0.9545, "recall": 0.9545, "field_accuracy": 0.95, "exact_match_rate": 0.6}, "合計")
    issues = [[(i["index"], i["reason"]) for i in found] for _, found in results[3:]]
    eq(issues, [[(1, "unknown_name"), (4, "low_confidence"), (4, "unknown_name")], [(None, "total_mismatch")]],
       "誤りの例の要確認")
    return "適合率 0.9545・再現率 0.9545・項目一致率 0.95・完全一致率 0.6／卵 3≠4 は要確認に出ない"


@check("V6 CER の集計：文字数加重と単純平均（計算例）と、10文の正解の文字数")
def _():
    pairs = [
        (SENTENCES[1], "冷蔵庫に卵と牛乳とニンジンがあります"),
        (SENTENCES[6], "小麦を使わない番模範を探して"),
        (SENTENCES[7], SENTENCES[7]),
    ]
    eq(aggregate(pairs), {"cer_weighted": 0.143, "cer_weighted_relaxed": 0.071, "cer_mean": 0.163,
                          "cer_mean_relaxed": 0.089}, "3文の集計")
    eq(sum(len(normalize_ja(t)) for t in SENTENCES), 166, "10文の正解の文字数")
    return "加重 0.143・平均 0.163／ゆれ吸収 加重 0.071・平均 0.089／10文で 166 文字"


@check("V7 パーセンタイル（最近傍順位法）は実際に測った値を返し、numpy の inverted_cdf と一致する")
def _():
    eq([percentile(range(1, 11), 50), percentile(range(1, 11), 95), percentile(range(1, 21), 95), percentile([7], 95)],
       [5, 10, 19, 7], "p50・p95")
    shuffled = list(range(1, 21))
    random.Random(12).shuffle(shuffled)
    eq(percentile(shuffled, 95), 19, "並び順に依らない")
    for values in ([3, 1, 2], list(range(1, 21)), [100] * 18 + [1000] * 2):
        for p in (50, 90, 95, 99):
            eq(percentile(values, p), int(np.percentile(values, p, method="inverted_cdf")), f"numpy と比較 p{p}")
    eq(latency_summary([100] * 18 + [1000] * 2),
       {"n": 20, "mean_ms": 190, "p50_ms": 100, "p95_ms": 1000, "max_ms": 1000}, "平均と p50・p95")
    for bad in (([], 50), ([1], 0), ([1], 101)):
        try:
            percentile(*bad)
            raise AssertionError(f"{bad} が通ってしまった")
        except ValueError:
            pass
    return "1〜10 の p95＝10（最大）・1〜20 の p95＝19／100ms×18＋1000ms×2 は平均 190・p50 100・p95 1000"


@check("V8 回帰の判定は決定的な指標だけで行い、遅延はどれだけ変わっても参考表示にとどめる")
def _():
    ext = {"precision": 1.0, "recall": 1.0, "field_accuracy": 1.0, "exact_match_rate": 1.0}
    cer = {"cer_weighted": 0.084, "cer_weighted_relaxed": 0.048}
    base = build_report(ext, cer, {"stt": {"p50_ms": 1900, "p95_ms": 2100}})
    eq(find_regressions(base, base), [], "同じ結果")
    worse = build_report({**ext, "precision": 0.9545}, cer, None)
    eq(find_regressions(worse, base), ["extraction.precision：1.0 → 0.9545（悪化。許容幅 0.0）"], "抽出の悪化")
    eq(find_regressions(build_report(ext, {**cer, "cer_weighted": 0.09}, None), base), [], "CER の許容幅の内側")
    eq(find_regressions(build_report(ext, {**cer, "cer_weighted": 0.1}, None), base),
       ["cer.weighted_strict：0.084 → 0.1（悪化。許容幅 0.01）"], "CER の悪化")
    high = build_report(ext, {**cer, "cer_weighted": 0.16}, None)
    eq(find_regressions(high, high), ["cer.weighted_strict：0.16 が上限 0.15 を超えました"], "CER の上限")
    slow = build_report(ext, cer, {"stt": {"p50_ms": 3800, "p95_ms": 4200}})
    eq(find_regressions(slow, base), [], "遅延が2倍でも回帰にしない")
    eq(latency_notes(slow, base)[1], "latency.stt.p95_ms：2100 → 4200（参考。合否に使わない）", "遅延の表示")
    return "抽出 1.0→0.9545 は回帰・CER +0.006 は許容・+0.016 は回帰・0.16 は上限超え・遅延 2倍は参考"


@check("V9 実機の閉ループ（small・int8・beam 1）で、10文の加重 CER が 0.15 以下")
def _():
    clips = asyncio.run(eval_cer.synthesize_all(SENTENCES))
    row = eval_cer.evaluate_config(clips, "small", "int8", 1, 2)
    eq(len(row["transcripts"]), 10, "認識した文の数")
    assert row["cer_weighted"] <= 0.15, row
    assert row["cer_weighted_relaxed"] <= row["cer_weighted"], row
    assert 0 <= row["cer_mean_relaxed"] <= row["cer_mean"], row
    return "加重 CER ≤ 0.15・ゆれ吸収 ≤ 厳密"


@check("V10 遅延の計測は準備の1回を除いて n 回を集計する（時間そのものは合否にしない）")
async def _():
    await mock("POST", "/_mock/reset")
    s = (await eval_latency.run(["fridge_scan"], repeat=3))["fridge_scan"]
    eq((s["n"], len(s["samples_ms"])), (3, 3), "集計した回数")
    assert s["p50_ms"] <= s["p95_ms"] == s["max_ms"], s
    eq((await mock("GET", "/_mock/stats"))["by_scenario"], {"fridge_photo": 4}, "mockllm への送信（準備1＋3）")
    return "n=3（p95＝最大値）・mockllm への送信 4 回"


finish("session12")
