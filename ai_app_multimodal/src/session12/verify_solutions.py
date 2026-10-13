"""セッション12：練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session12

決定的な計算だけを確かめる（Whisper・VOICEVOX は使わない）。問題5・6は表の組み立てと判定の関数を確かめる。
"""

from __future__ import annotations

from src.session12.eval_cer import SENTENCES, aggregate
from src.session12.evaluate import build_report
from src.session12.gold import Gold, fridge_gold, receipt_gold
from src.session12.matching import ratio
from src.session12.solutions import q1_hand_score, q2_cer_hand, q3_percentiles, q4_aliases, q5_table, q6_dataset_guard
from src.session12.solutions import q7_breakdown, q8_plan
from src.session12.eval_latency import summarize
from src.session12.matching import norm_name, score_case
from kondate.verifykit import check, eq, finish


@check("S1 手で採点：重複は余計・ニンジンはにんじんと組になり、数量 2≠1 は項目の誤り")
def _():
    s = score_case("問題1", fridge_gold(), q1_hand_score.PRED)
    eq((s.predicted, s.gold, s.matched, s.fields_correct, s.fields_checked, s.exact), (6, 5, 4, 2, 3, False), "件数")
    eq((ratio(s.matched, s.predicted), ratio(s.matched, s.gold)), (0.6667, 0.8), "適合率・再現率")
    eq(s.errors, ("にんじん の amount：2 ≠ 1", "余計：卵", "余計：バター", "見逃し：鶏むね肉"), "誤り")
    return "適合率 0.6667・再現率 0.8・項目 2/3"


@check("S2 4文の CER：加重 0.111・平均 0.099、ゆれ吸収はどちらも 0.056")
def _():
    eq(aggregate(q2_cer_hand.PAIRS), {"cer_weighted": 0.111, "cer_weighted_relaxed": 0.056, "cer_mean": 0.099,
                                      "cer_mean_relaxed": 0.056}, "集計")
    return "厳密 8/72＝0.111・平均 0.099／ゆれ吸収 4/72＝0.056・平均 0.056"


@check("S3 架空の20ターン：平均 6033・p50 5710・p95 8840／10ターンでは p95 が最大値 9120")
def _():
    eq(summarize(q3_percentiles.FIRST_AUDIO_MS),
       {"n": 20, "mean_ms": 6033, "p50_ms": 5710, "p95_ms": 8840, "max_ms": 9120}, "20ターン")
    eq(summarize(q3_percentiles.FIRST_AUDIO_MS[:10]),
       {"n": 10, "mean_ms": 6050, "p50_ms": 5710, "p95_ms": 9120, "max_ms": 9120}, "10ターン")
    eq(q3_percentiles.linear_p95(q3_percentiles.FIRST_AUDIO_MS), 8854, "線形補間の p95")
    return "最近傍順位 8840／線形補間 8854（測っていない値）"


@check("S4 別名を足すと 3/5 → 5/5。キーをカタカナで書くと「ミルク」は一致しない")
def _():
    def got(norm):
        s = q4_aliases.run(norm)
        return (s.matched, s.fields_correct, s.fields_checked, s.exact)
    eq(got(norm_name), (3, 2, 2, False), "別名なし")
    eq(got(q4_aliases.with_aliases(q4_aliases.ALIASES)), (5, 4, 4, True), "別名あり")
    eq(got(q4_aliases.with_aliases({"玉子": "卵", "ミルク": "牛乳"})), (4, 3, 3, False), "カタカナのキー")
    return "一致 3 → 5（完全一致）・カタカナのキーでは 4"


@check("S5 比較表：加重 CER が同じなら beam の小さい行に ◎ が付く")
def _():
    rows = [
        {"model": "small", "compute_type": "int8", "beam": 5, "cer_weighted": 0.084, "cer_weighted_relaxed": 0.048,
         "cer_mean": 0.08, "cer_mean_relaxed": 0.049},
        {"model": "small", "compute_type": "int8", "beam": 1, "cer_weighted": 0.084, "cer_weighted_relaxed": 0.048,
         "cer_mean": 0.08, "cer_mean_relaxed": 0.049},
        {"model": "base", "compute_type": "int8", "beam": 1, "cer_weighted": 0.3, "cer_weighted_relaxed": 0.25,
         "cer_mean": 0.31, "cer_mean_relaxed": 0.26},
    ]
    lines = q5_table.markdown_table(rows).splitlines()
    eq(lines[:2], q5_table.HEADER, "見出し")
    eq(lines[2:], [
        "| ◎ | small | int8 | 1 | 0.084 | 0.048 | 0.080 | 0.049 |",
        "|  | small | int8 | 5 | 0.084 | 0.048 | 0.080 | 0.049 |",
        "|  | base | int8 | 1 | 0.300 | 0.250 | 0.310 | 0.260 |",
    ], "行")
    return "small・beam 1 に ◎（同じ CER なら速い方）"


@check("S6 評価セットの指紋：同じ入力なら同じ値、文や正解が変われば別の値。違えば比べずに 2 を返す")
def _():
    fp = q6_dataset_guard.fingerprint()
    eq((len(fp), fp == q6_dataset_guard.fingerprint()), (12, True), "長さと再現性")
    changed = list(SENTENCES[:-1]) + ["今日は和食がいいな。"]
    eq(fp == q6_dataset_guard.fingerprint(sentences=changed), False, "文を変えたとき")
    g = fridge_gold()
    other = Gold(g.media, g.items[:-1], g.header)
    golds = [other, receipt_gold("receipt.png"), receipt_gold("receipt.pdf")]
    eq(fp == q6_dataset_guard.fingerprint(golds), False, "正解を変えたとき")
    ext = {"precision": 1.0, "recall": 1.0, "field_accuracy": 1.0, "exact_match_rate": 1.0}
    cer = {"cer_weighted": 0.084, "cer_weighted_relaxed": 0.048}
    base = {**build_report(ext, cer, None), "dataset": fp}
    eq(q6_dataset_guard.judge(base, base), (0, []), "同じ評価セット・同じ結果")
    worse = {**build_report({**ext, "recall": 0.8}, cer, None), "dataset": fp}
    eq(q6_dataset_guard.judge(worse, base)[0], 1, "同じ評価セット・悪化")
    eq(q6_dataset_guard.judge({**worse, "dataset": "000000000000"}, base),
       (2, [q6_dataset_guard.MSG_DATASET]), "評価セットが違う")
    return "指紋 12 桁・文や正解を変えると別の値・違えば終了コード 2"


@check("S7 内訳：平均と p50 では tts_first、p95 では llm_first_sentence が最も長い")
def _():
    table = q7_breakdown.breakdown(q7_breakdown.sample_turns())
    eq(table["llm_first_sentence"], {"n": 20, "mean_ms": 1355, "p50_ms": 800, "p95_ms": 4500, "max_ms": 4500}, "LLM")
    eq((table["first_audio"]["p50_ms"], table["first_audio"]["p95_ms"], table["first_audio"]["mean_ms"]),
       (6380, 10080, 6935), "first_audio")
    eq([q7_breakdown.dominant(table, k) for k in ("mean_ms", "p50_ms", "p95_ms")],
       ["tts_first", "tts_first", "llm_first_sentence"], "最も長い項目")
    return "平均・p50 → tts_first／p95 → llm_first_sentence"


@check("S8 見積もり：30件×3回＝90回・input 150,120・最悪（再試行込み）180回・input 300,240")
def _():
    eq(q8_plan.plan(30, 3, 1668, 194), {
        "calls": 90, "input_tokens": 150120, "output_tokens": 17460,
        "worst_calls": 180, "worst_input_tokens": 300240, "worst_output_tokens": 34920,
    }, "見積もり")
    return "90回・150,120／17,460 トークン（最悪 180回・300,240／34,920）"


finish("session12 solutions")
