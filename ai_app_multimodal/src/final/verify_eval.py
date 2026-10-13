"""最終プロジェクトの検証④：評価スクリプト（src/final/evaluate.py）の決定的な部分。

    docker compose exec api bash verify-all.sh src/final

抽出の正解率は mockllm と FakeProvider で入口から測り、セッション12と同じ値になることを確かめる。
CER と遅延は時間がかかる・環境で変わるので、ここでは測らない（python -m src.final.evaluate で測る）。
"""

from __future__ import annotations

from kondate.clock import FixedClock
from kondate.verifykit import check, eq, finish
from src.final.evaluate import (RULES, build_report, error_cases, find_regressions, mock_cases, percentile, run_cases,
                                summarize_ms)
from src.final.matching import summarize
from src.final.testkit import OUT, mock, running


@check("V1 入口から測る抽出（mockllm）：3件とも完全一致、4指標とも 1.0")
async def _():
    await mock("POST", "/_mock/reset")
    async with running(clock=FixedClock(), out=OUT / "eval_v1") as c:
        results = await run_cases(c, mock_cases())
    rows = [(s.predicted, s.gold, s.matched, s.exact) for s, _ in results]
    eq(rows, [(5, 5, 5, True), (4, 4, 4, True), (4, 4, 4, True)], "ケースごと（予測・正解・一致・完全一致）")
    eq(summarize(s for s, _ in results),
       {"cases": 3, "precision": 1.0, "recall": 1.0, "field_accuracy": 1.0, "exact_match_rate": 1.0}, "合計")
    return "fridge.jpg 5/5・receipt.png 4/4・receipt.pdf 4/4／適合率・再現率・項目一致率・完全一致率 1.0"


@check("V2 誤りを含む応答を混ぜると、採点器が誤りを数える（セッション12と同じ 0.9545・0.9545・0.95・0.6）")
async def _():
    async with running(clock=FixedClock(), out=OUT / "eval_v2") as c:
        results = await run_cases(c, mock_cases() + error_cases())
    total = summarize(s for s, _ in results)
    eq(total, {"cases": 5, "precision": 0.9545, "recall": 0.9545, "field_accuracy": 0.95, "exact_match_rate": 0.6},
       "合計")
    reasons = [sorted({i["reason"] for i in issues}) for _, issues in results[3:]]
    eq(reasons, [["low_confidence", "unknown_name"], ["total_mismatch"]], "誤りの例の要確認")
    return "5件：適合率 0.9545・再現率 0.9545・項目一致率 0.95・完全一致率 0.6／要確認の印も付く"


@check("V3 p95 は最近傍順位法（n=20 で19番目・n=19 では最大値と同じ）")
def _():
    eq((percentile(list(range(1, 21)), 50), percentile(list(range(1, 21)), 95)), (10, 19), "n=20")
    eq(percentile(list(range(1, 20)), 95), 19, "n=19")
    eq(summarize_ms([300, 100, 200]), {"n": 3, "mean_ms": 200, "p50_ms": 200, "p95_ms": 300, "max_ms": 300}, "集計")
    return "n=20：p50 10・p95 19／n=19：p95 は最大値／3件の集計"


@check("V4 基準との比較：決定的な指標だけで判定し、遅延（環境依存）は回帰にしない")
def _():
    extraction = {"precision": 1.0, "recall": 1.0, "field_accuracy": 1.0, "exact_match_rate": 1.0}
    base = build_report(extraction, {"cer_weighted": 0.084, "cer_weighted_relaxed": 0.048},
                        {"stt": {"p50_ms": 1700, "p95_ms": 2070}})
    slower = build_report(extraction, {"cer_weighted": 0.09, "cer_weighted_relaxed": 0.048},
                          {"stt": {"p50_ms": 3400, "p95_ms": 4100}})
    worse = build_report({**extraction, "recall": 0.9545}, {"cer_weighted": 0.2, "cer_weighted_relaxed": 0.048}, None)
    no_cer = build_report(extraction, None, None)
    eq(find_regressions(slower, base), [], "CER +0.006・遅延 2倍")
    eq(find_regressions(worse, base), [
        "extraction.recall：1.0 → 0.9545（悪化。許容幅 0.0）",
        "cer.weighted_strict：0.2 が上限 0.15 を超えました",
        "cer.weighted_strict：0.084 → 0.2（悪化。許容幅 0.01）",
    ], "再現率の低下と CER の悪化")
    eq(find_regressions(no_cer, base, {k: r for k, r in RULES.items() if k in no_cer["deterministic"]}), [],
       "CER を測らなかったときは CER を比べない")
    return "CER +0.006 と遅延 2倍は回帰なし／再現率の低下・CER 0.2 は回帰 3 件／測らなかった CER は比べない"


finish("final-eval")
