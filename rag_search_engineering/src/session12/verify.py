#!/usr/bin/env python3
"""セッション12の自己検証：RAG 全体の評価が決定的に回ること。

APIキーは使わない（合成カセットを再生するだけ）。
埋め込みモデルもリランカも使わないので CPU だけで完走する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import (LAYERS, MAX_CHARS, TOP_K, Bench, collect_cases,  # noqa: E402
                      layer_counts, pearson)
from make_gold_cassette import CASSETTE, build  # noqa: E402
from report import build_report, to_markdown  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, answer_with_citations, build_user_prompt, verify_citations  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


bench = Bench()
answerable = bench.answerable_queries()
unanswerable = [q for q in bench.queries if q.type == "unanswerable"]

# --- 前提（カセットと条件が揃っていること）---------------------------------
check("チャンク方式が fixed(400/80) で 673 チャンク", len(bench.chunks) == 673,
      f"{len(bench.chunks)} チャンク")
check("クエリ 120 件・回答可能 110 件",
      len(bench.queries) == 120 and len(answerable) == 110,
      f"{len(bench.queries)} 件 / 回答可能 {len(answerable)} 件")
check("回答不能クエリは判定データに適合文書を持たない",
      all(not any(g >= 1 for g in bench.qrels_for(q).values()) for q in unanswerable),
      f"{len(unanswerable)} 件")

# --- 上限測定の入力（正解チャンク）-----------------------------------------
bad_gold = [q.query_id for q in answerable
            if any(bench.qrels_for(q).get(h.doc_id, 0) < 1 for h in bench.gold_hits(q))]
check("正解チャンクは判定データの適合文書だけから作られる", not bad_gold, f"逸脱 {len(bad_gold)} 件")
check("正解チャンクは上位件数を超えない",
      all(len(bench.gold_hits(q)) <= TOP_K for q in answerable))
check("回答不能クエリの正解チャンクは0件",
      all(bench.gold_hits(q) == [] for q in unanswerable))

# --- 合成カセットの生成 -----------------------------------------------------
path = build(bench)
cassette = json.loads(path.read_text(encoding="utf-8"))
check("上限測定用の合成カセットを生成できた", len(cassette) == len(bench.queries),
      f"{len(cassette)} 件")

normal = FixtureClient("answers_v1")
misses = 0
for q in bench.queries[:30]:
    try:
        normal.complete(
            SYSTEM_PROMPT, build_user_prompt(q.text, bench.gold_hits(q), max_chars=MAX_CHARS))
    except KeyError:
        misses += 1
check("コンテキストを変えると既存カセットが当たらなくなる", misses > 0, f"{misses}/30 件が KeyError")

# --- 3層の切り分け ----------------------------------------------------------
retrieved = collect_cases(bench, normal)
counts = layer_counts(retrieved)
check("全ケースがちょうど1つの層に分類される",
      sum(counts.values()) == len(retrieved) and all(c.layer in LAYERS for c in retrieved),
      f"{counts}")
check("コーパス起因に分類されるのは回答不能クエリだけ",
      all(c.query_type == "unanswerable" for c in retrieved if c.layer == "corpus")
      and counts["corpus"] == 10, f"{counts['corpus']} 件")
check("検索起因のケースが検出される", counts["retrieval"] > 0, f"{counts['retrieval']} 件")

# --- 上限測定 ---------------------------------------------------------------
upper = {c.query_id: c for c in collect_cases(bench, FixtureClient(CASSETTE), gold=True)}
recovered = [c.query_id for c in retrieved
             if c.layer == "retrieval" and upper[c.query_id].layer == "ok"]
stubborn = [qid for qid, c in upper.items() if c.layer != "ok" and c.query_type != "unanswerable"]
check("検索起因のケースは正解チャンクを渡すと成功に変わる", len(recovered) > 0,
      f"{len(recovered)}/{counts['retrieval']} 件が回復")
check("正解チャンクを渡しても失敗するケースがある（生成起因）", len(stubborn) > 0,
      f"{len(stubborn)} 件")

# --- 忠実性・根拠一致・回答可能性 -------------------------------------------
flawed = FixtureClient("answers_flawed_v1")
no_citation = fake_citation = 0
for q in bench.queries[:30]:
    hits = bench.retrieved_hits(q)
    ans = answer_with_citations(flawed, q.text, hits)
    _, invalid = verify_citations(ans, hits)
    if not ans.citations:
        no_citation += 1
    elif invalid:
        fake_citation += 1
check("引用なしの応答を検出できる", no_citation == 10, f"{no_citation} 件")
check("存在しない chunk_id の引用を検出できる", fake_citation == 10, f"{fake_citation} 件")

flawed_cases = collect_cases(bench, flawed)
valid_faith = [c.judgement.faithfulness for c in retrieved
               if c.judgement.answerable and c.judgement.citations_valid]
invalid_faith = [c.judgement.faithfulness for c in flawed_cases
                 if c.judgement.answerable and not c.judgement.citations_valid]
mean_valid = sum(valid_faith) / len(valid_faith) if valid_faith else 0.0
mean_invalid = sum(invalid_faith) / len(invalid_faith) if invalid_faith else 0.0
check("忠実性は引用が有効なケースで高く、無効なケースで 0 になる",
      mean_valid > mean_invalid and mean_invalid == 0.0,
      f"有効 {mean_valid:.3f} / 無効 {mean_invalid:.3f}")

abstained = sum(1 for c in retrieved if c.query_type == "unanswerable" and not c.judgement.answerable)
check("回答不能クエリで回答不能と判定される", abstained == len(unanswerable),
      f"{abstained}/{len(unanswerable)} 件")

# --- 代理指標の妥当性 -------------------------------------------------------
rep = evaluate(bench.index, bench.queries, bench.qrels, k=10, label="bm25/fixed")
by_id = {c.query_id: c for c in retrieved}
pairs = [(rep.per_query[qid]["recall"], by_id[qid]) for qid in rep.per_query if qid in by_id]
r = pearson([x for x, _ in pairs], [1.0 if c.layer == "ok" else 0.0 for _, c in pairs])
check("Recall@10 と回答成功に正の相関がある", r > 0.0, f"r = {r:+.3f}")
check("基準線の Recall@10 が 0.763", abs(rep.macro["recall"] - 0.763) < 0.001,
      f"{rep.macro['recall']:.3f}")

# --- レポート（引き継げる成果物）-------------------------------------------
data = build_report(bench)
need = ("corpus_layer", "retrieval_layer", "generation_layer", "proxy_check", "upper_bound")
check("レポートに層ごとの節が揃っている", all(key in data for key in need))
check("レポートが JSON として往復できる",
      json.loads(json.dumps(data, ensure_ascii=False))["layer_counts"] == data["layer_counts"])
check("Markdown レポートに読み手の表がある", "| 読み手 | 何を判断するか | 見る数字 |" in to_markdown(data))

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション12の検証はすべて成功しました。")
