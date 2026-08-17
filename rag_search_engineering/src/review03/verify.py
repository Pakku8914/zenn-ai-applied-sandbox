#!/usr/bin/env python3
"""横断復習03（セッション9〜12・間隔反復で2〜8も）の自己検証。

  1. 失敗の分解表の算術が閉じていること（S02 × Review01 × S09 × S10）
  2. コンテキストは先頭から連続してしか載らないこと（S11 × S04）
  3. 引用検証で4つの結末に仕分けられること（S11 × S12）
  4. 失敗を3層に切り分け、上限を測れること（S12 × S11 × S03）
  5. カセットの鍵が検索条件に依存すること（S09 × S11 × S12）
  6. 打ち手とコストの表が「測っていない」を保てること（S05〜S10）

APIキーも埋め込みモデルも Qdrant も使わない（BM25 と合成カセットだけで回る）。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from budget_table import (  # noqa: E402
    MEASURED_RECALL, MOVE_COST, max_candidates, per_item_ms, pipeline_ms,
    recall_evidence, rerank_ms, rerank_share,
)
from cassette_guard import key_of, replay  # noqa: E402
from failure_math import (  # noqa: E402
    ALL, SPLIT, ceiling_for_type, ceiling_rank_fixed, contribution, dominant,
    moves_for, overall_after, rank_loss, reach_loss, weighted_mean,
)
from layer_lab import (  # noqa: E402
    OracleRetriever, TOP_K, abstention_check, answerable, bm25_index,
    context_recall, included_hits, layer_split, load_all, mean_included,
    outcome_counts, unanswerable,
)

from ragkit.answer import SYSTEM_PROMPT, build_context  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    shown = f"{got:.4f}" if isinstance(want, float) else got
    print(f"[{'OK' if ok else 'NG'}] {label}: got={shown} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


# ---------------------------------------------------------------------------
# 1. 失敗の分解と打ち手の層 — S02 × Review01 × S09 × S10
# ---------------------------------------------------------------------------
print("--- 1. 失敗の分解と打ち手の層 ---")

check("件数で重み付けした Recall@10 が ALL と一致", weighted_mean("recall"), 0.763, 0.002)
check("件数で重み付けした 到達@100 が ALL と一致", weighted_mean("reach"), 0.885, 0.002)

for qtype, row in list(SPLIT.items()) + [("ALL", ALL)]:
    total = row["recall"] + rank_loss(row) + reach_loss(row)
    check_true(f"{qtype}: Recall@10 + 順位不足 + 到達不足 = 1", abs(total - 1.0) <= 0.002,
               f"{row['recall']:.3f} + {rank_loss(row):.3f} + {reach_loss(row):.3f} "
               f"= {total:.3f}")

check_true("略語は到達不足が支配的（候補にすら入っていない）",
           dominant(SPLIT["abbrev"]) == "reach"
           and reach_loss(SPLIT["abbrev"]) > 2 * rank_loss(SPLIT["abbrev"]),
           f"到達不足 {reach_loss(SPLIT['abbrev']):.3f} 対 "
           f"順位不足 {rank_loss(SPLIT['abbrev']):.3f}")
check_true("だから略語にリランクを当てても原理的に届かない",
           "リランク（クロスエンコーダ）" not in moves_for(SPLIT["abbrev"]),
           " / ".join(moves_for(SPLIT["abbrev"])))
check_true("複数条件は順位不足が支配的（候補には居る）",
           dominant(SPLIT["multi_condition"]) == "rank"
           and rank_loss(SPLIT["multi_condition"]) > 5 * reach_loss(SPLIT["multi_condition"]),
           f"順位不足 {rank_loss(SPLIT['multi_condition']):.3f} 対 "
           f"到達不足 {reach_loss(SPLIT['multi_condition']):.3f}")
check_true("だから複数条件にはリランクが候補に挙がる",
           "リランク（クロスエンコーダ）" in moves_for(SPLIT["multi_condition"]))
check_true("ALL だけを見ると順位不足の方が大きく見える（平均だけ見ると打ち手を間違える）",
           rank_loss(ALL) > reach_loss(ALL),
           f"順位不足 {rank_loss(ALL):.3f} > 到達不足 {reach_loss(ALL):.3f}")

check("略語を 0.873 まで直したときの全体", overall_after("abbrev", 0.873), 0.889, 0.001)
check("複数条件の順位不足をゼロにしたときの全体", ceiling_for_type("multi_condition"),
      0.817, 0.001)
check("すべての順位不足をゼロにしたときの全体の上限", ceiling_rank_fixed(), 0.885, 0.001)
check_true("略語1型の語彙対策の寄与が、複数条件1型の並べ替えの上限より大きい",
           contribution("abbrev", 0.873) > contribution("multi_condition", 0.947),
           f"{contribution('abbrev', 0.873):+.3f} 対 "
           f"{contribution('multi_condition', 0.947):+.3f}")

# ---------------------------------------------------------------------------
# 2. コンテキストに載るのは先頭から連続した分だけ — S11 × S04
# ---------------------------------------------------------------------------
print("\n--- 2. コンテキスト予算 ---")

docs, queries, qrels, chunks = load_all()
index = bm25_index(chunks)
ans_queries = answerable(queries, qrels)

check("チャンク数（fixed(400/80)）", len(chunks), 673)
check("回答可能なクエリ数", len(ans_queries), 110)
check("回答不能なクエリ数", len(unanswerable(queries, qrels)), 10)
check_true("判定データ由来の回答不能クエリと type=unanswerable が一致する",
           {q.query_id for q in unanswerable(queries, qrels)}
           == {q.query_id for q in queries if q.type == "unanswerable"})

probe_q = ans_queries[0]
probe_hits = index.search(probe_q.text, k=10)
counts = []
for limit in (500, 1000, 2000, 4000):
    ctx = build_context(probe_hits, max_chars=limit)
    inc = included_hits(probe_hits, max_chars=limit)
    counts.append(len(inc))
    check_true(f"上限 {limit}字 を超えない", len(ctx) <= limit, f"{len(ctx)}字 / {len(inc)}件")
    check_true(f"上限 {limit}字: 載るのは先頭から連続した候補だけ",
               inc == probe_hits[:len(inc)])
check_true("上限を下げると載る件数は増えない", counts == sorted(counts),
           " -> ".join(str(c) for c in counts))

# 親子チャンク（S04）: 子で検索して親を渡すと、同じ2000字に載る件数が減る
parent_chunks = chunk_all(docs, "parent_window", child=200, window=600)
parent_index = LexicalIndex().build(parent_chunks)
check("チャンク数（parent_window(200/600)）", len(parent_chunks), 1007)
child_mean = mean_included(parent_index, ans_queries[:30], k=TOP_K, use_parent=False)
parent_mean = mean_included(parent_index, ans_queries[:30], k=TOP_K, use_parent=True)
check_true("親を渡すと、同じ2000字に載る候補が減る", parent_mean < child_mean,
           f"子 {child_mean:.2f}件 -> 親 {parent_mean:.2f}件")

check_true("上限を4000字に広げれば、より多くの候補が載る",
           mean_included(index, ans_queries[:30], k=10, max_chars=4000)
           > mean_included(index, ans_queries[:30], k=10, max_chars=2000))

# ---------------------------------------------------------------------------
# 3. 引用検証の4つの結末 — S11 × S12
# ---------------------------------------------------------------------------
print("\n--- 3. 引用検証の4つの結末 ---")

good = FixtureClient("answers_v1")
flawed = FixtureClient("answers_flawed_v1")

good_counts = outcome_counts(index, good, queries)
flawed_counts = outcome_counts(index, flawed, queries)
print(f"  正常系カセット: {good_counts}")
print(f"  異常系カセット: {flawed_counts}")

check("正常系カセットの合計", sum(good_counts.values()), 120)
check("正常系カセットに引用なしは無い", good_counts["no_citation"], 0)
check("正常系カセットに無効な引用は無い", good_counts["invalid_citation"], 0)
check("異常系カセットで回答不能と言った件数", flawed_counts["abstained"], 0)
check("異常系カセットの存在しない chunk_id の引用（DOC-9999）", flawed_counts["invalid_citation"], 40)
check_true("異常系カセットの引用なしは40件以上", flawed_counts["no_citation"] >= 40,
           f"{flawed_counts['no_citation']} 件")

strict_counts = outcome_counts(index, good, queries, strict=True)
print(f"  正常系カセット（コンテキストに載った分だけで検証）: {strict_counts}")
check_true("突き合わせ先を狭めると ok は増えない",
           strict_counts["ok"] <= good_counts["ok"],
           f"{good_counts['ok']} -> {strict_counts['ok']}")
check_true("突き合わせ先を狭めると無効な引用は減らない",
           strict_counts["invalid_citation"] >= good_counts["invalid_citation"])

abst_good = abstention_check(index, good, queries, qrels)
abst_flawed = abstention_check(index, flawed, queries, qrels)
check("回答不能クエリで正常系カセットが回答不能と判定した件数", abst_good["abstained"], 10)
check("回答不能クエリで異常系カセットが引用付きで答えた件数", abst_flawed["ok"], 0)
check("回答不能クエリで異常系カセットが回答不能と判定した件数", abst_flawed["abstained"], 0)
check_true("異常系の10件は引用検証だけで全部落とせる",
           abst_flawed["no_citation"] + abst_flawed["invalid_citation"] == 10,
           f"引用なし {abst_flawed['no_citation']} 件 / "
           f"無効な引用 {abst_flawed['invalid_citation']} 件")

# ---------------------------------------------------------------------------
# 4. 失敗の3層と上限測定 — S12 × S11 × S03
# ---------------------------------------------------------------------------
print("\n--- 4. 失敗の3層と上限測定 ---")

split2 = layer_split(index, good, queries, qrels, min_grade=2)
split1 = layer_split(index, good, queries, qrels, min_grade=1)
print("  grade>=2 でそろえた層: " + ", ".join(f"{k} {len(v)}" for k, v in split2.items()))
print("  grade>=1 にずらした層: " + ", ".join(f"{k} {len(v)}" for k, v in split1.items()))

check("3層の合計が回答可能クエリ数と一致（grade>=2）", sum(len(v) for v in split2.values()), 110)
check("3層の合計が回答可能クエリ数と一致（grade>=1）", sum(len(v) for v in split1.values()), 110)
check("正常系カセットでは生成層の失敗が0件（＝生成の質はこれで測れない）",
      len(split2["generation"]), 0)
check_true("しきい値をゆるめると検索層の失敗は増えない",
           len(split1["retrieval"]) <= len(split2["retrieval"]),
           f"{len(split2['retrieval'])} -> {len(split1['retrieval'])}")
check_true("しきい値をゆるめると成功は減らない",
           len(split1["ok"]) >= len(split2["ok"]),
           f"{len(split2['ok'])} -> {len(split1['ok'])}")

oracle = OracleRetriever(chunks, queries, qrels)
cr_bm25_5 = context_recall(index, ans_queries, qrels, k=5)
cr_bm25_10 = context_recall(index, ans_queries, qrels, k=10)
cr_oracle = context_recall(oracle, ans_queries, qrels, k=5)
print(f"  コンテキストに適合文書が載った割合: bm25 上位5件 {cr_bm25_5['ALL']['rate']:.3f} / "
      f"bm25 上位10件 {cr_bm25_10['ALL']['rate']:.3f} / "
      f"オラクル {cr_oracle['ALL']['rate']:.3f} (n={int(cr_oracle['ALL']['n'])})")

check("オラクルなら必ず載る（検索層の失敗をゼロにした世界）", cr_oracle["ALL"]["rate"], 1.0, 1e-9)
check_true("実際の検索では載らないクエリがある", 0.0 < cr_bm25_5["ALL"]["rate"] < 1.0)
check_true("候補を10件に増やしても、載る割合はほとんど変わらない（2000字が先に埋まる）",
           cr_bm25_10["ALL"]["rate"] >= cr_bm25_5["ALL"]["rate"],
           f"{cr_bm25_5['ALL']['rate']:.3f} -> {cr_bm25_10['ALL']['rate']:.3f}")
check_true("型別の集計に abbrev と keyword がある",
           "abbrev" in cr_bm25_5 and "keyword" in cr_bm25_5)
check_true("略語クエリはコンテキストに載る割合も低い",
           cr_bm25_5["abbrev"]["rate"] < cr_bm25_5["keyword"]["rate"],
           f"abbrev {cr_bm25_5['abbrev']['rate']:.3f} < "
           f"keyword {cr_bm25_5['keyword']['rate']:.3f}")

# ---------------------------------------------------------------------------
# 5. カセットの鍵は検索条件に依存する — S09 × S11 × S12
# ---------------------------------------------------------------------------
print("\n--- 5. カセットの鍵 ---")

hits5 = index.search(probe_q.text, k=TOP_K)
check_true("同じ入力なら鍵は同じ", key_of(probe_q.text, hits5) == key_of(probe_q.text, hits5))
check_true("順位を入れ替えるだけで鍵が変わる（リランクを足すとカセットが無効になる）",
           key_of(probe_q.text, list(reversed(hits5))) != key_of(probe_q.text, hits5))
check_true("システムプロンプトに空白を1つ足すだけで鍵が変わる",
           key_of(probe_q.text, hits5, system=SYSTEM_PROMPT + " ")
           != key_of(probe_q.text, hits5))
check_true("基準の入力はカセットから再生できる",
           replay(good, probe_q.text, hits5).source == "fixture")
try:
    replay(good, probe_q.text, list(reversed(hits5)))
    check_true("順位を入れ替えた入力は KeyError になる", False, "例外が出なかった")
except KeyError:
    check_true("順位を入れ替えた入力は KeyError になる", True)

# ---------------------------------------------------------------------------
# 6. 打ち手とコストの表 — S05 × S06 × S07 × S08 × S09 × S10
# ---------------------------------------------------------------------------
print("\n--- 6. 打ち手とコスト ---")

check("候補10の1件あたり", per_item_ms(10), 40.5, 0.05)
# 709 / 20 = 35.45。実測表の 35.4 は小数第1位への丸めなので、許容差を丸め幅より広く取る
check("候補20の1件あたり", per_item_ms(20), 35.4, 0.06)
check("候補50の1件あたり", per_item_ms(50), 31.4, 0.05)
check("候補100の1件あたり", per_item_ms(100), 27.1, 0.05)
check_true("候補を増やすと1件あたりは安くなる",
           per_item_ms(10) > per_item_ms(20) > per_item_ms(50) > per_item_ms(100))
check_true("それでも総額は増える",
           rerank_ms(10) < rerank_ms(20) < rerank_ms(50) < rerank_ms(100))

check("予算500ms（1段目に20ms）の上限候補数", max_candidates(500.0)[0], 12)
check("予算1,000ms の上限候補数", max_candidates(1000.0)[0], 29)
check("予算3,000ms の上限候補数", max_candidates(3000.0)[0], 111)
check_true("予算500ms・1,000ms の答えは測定点の内側",
           max_candidates(500.0)[1] and max_candidates(1000.0)[1])
check_true("予算3,000ms の答えは測定点の外側（外挿なので採用の根拠にしない）",
           not max_candidates(3000.0)[1])
check_true("予算300ms ではリランクを入れられない", max_candidates(300.0)[0] < 10,
           f"上限 {max_candidates(300.0)[0]} 件")

check_true("候補12の Recall@10 は測っていない", recall_evidence(12) is None)
check_true("候補29の Recall@10 も測っていない", recall_evidence(29) is None)
check("候補50の Recall@10 は測ってある", recall_evidence(50)[1], 0.818, 1e-9)
check_true("候補100 はレイテンシだけ測って精度は測っていない",
           recall_evidence(100) is None and rerank_ms(100) == 2710.0)

check_true("候補50のときレイテンシの98%以上をリランクが占める", rerank_share(50) > 0.98,
           f"{rerank_share(50):.4f}（合計 {pipeline_ms(50):.1f} ms）")
check_true("レイテンシを払わない打ち手（クエリ側同義語 0.889）の方が、"
           "1.5秒払うリランク（0.818）より Recall@10 が高い",
           MEASURED_RECALL["bm25 + クエリ側同義語展開"][0]
           > MEASURED_RECALL["dense → rerank(候補50)"][0])
check_true("ただし基準線が違うので差を足し引きしてはいけない",
           MEASURED_RECALL["bm25 + クエリ側同義語展開"][1]
           != MEASURED_RECALL["dense → rerank(候補50)"][1],
           f"{MEASURED_RECALL['bm25 + クエリ側同義語展開'][1]} 対 "
           f"{MEASURED_RECALL['dense → rerank(候補50)'][1]}")
check("打ち手の行数", len(MOVE_COST), 9)
check_true("表のすべての行に効く層と追加レイテンシがある",
           all(row[1] and isinstance(row[4], float) for row in MOVE_COST))

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n横断復習03の検証はすべて成功しました。")
