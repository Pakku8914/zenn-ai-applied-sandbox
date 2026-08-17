#!/usr/bin/env python3
"""セッション2の自己検証：評価指標の実装が正しいこと・基準線の数値が再現すること。

期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import (  # noqa: E402
    evaluate, hits_to_docs, mrr, ndcg_at_k, precision_at_k, recall_at_k,
)
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk, Hit

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"{'OK ' if ok else 'NG '} {label}: got={got} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, ok: bool) -> None:
    """真偽だけを見る検証（値そのものより関係が大事な項目に使う）。"""
    print(f"{'OK ' if ok else 'NG '} {label}")
    if not ok:
        failures.append(label)


def h(doc_id: str, score: float = 1.0) -> Hit:
    return Hit(chunk_id=f"{doc_id}#001", doc_id=doc_id, score=score, text="", meta={})


# --- 指標の単体検証（手で計算できる例）-------------------------------------
hits = [h("D1"), h("D2"), h("D3"), h("D4")]
qrels = {"D2": 2, "D4": 1, "D9": 2}  # 適合3件のうち2件が上位4件に入っている

check("hits_to_docs", hits_to_docs(hits), ["D1", "D2", "D3", "D4"])
check("recall@4", recall_at_k(hits, qrels, 4), 2 / 3, 1e-9)
check("recall@2", recall_at_k(hits, qrels, 2), 1 / 3, 1e-9)
check("precision@4", precision_at_k(hits, qrels, 4), 0.5, 1e-9)
check("mrr（2位が最初の適合）", mrr(hits, qrels), 0.5, 1e-9)

# nDCG@4: DCG = 0/log2(2) + 2/log2(3) + 0/log2(4) + 1/log2(5)
#         iDCG = 2/log2(2) + 2/log2(3) + 1/log2(4)
import math  # noqa: E402

dcg = 2 / math.log2(3) + 1 / math.log2(5)
idcg = 2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
check("ndcg@4", ndcg_at_k(hits, qrels, 4), dcg / idcg, 1e-9)

# 同一文書の複数チャンクが重複して数えられないこと
dup = [Hit("D1#001", "D1", 2.0, "", {}), Hit("D1#002", "D1", 1.5, "", {}), h("D2")]
check("重複チャンクの畳み込み", hits_to_docs(dup), ["D1", "D2"])

# 適合文書が無いクエリでは 0 になること
check("適合なしの recall", recall_at_k(hits, {}, 10), 0.0, 1e-9)
check("適合なしの ndcg", ndcg_at_k(hits, {}, 10), 0.0, 1e-9)

# --- 基準線の再現（BM25 / fixed(400,80)）------------------------------------
docs, queries, qrels_all = load_docs(), load_queries(), load_qrels()
check("文書数", len(docs), 301)
check("クエリ数", len(queries), 120)

chunks = chunk_all(docs, "fixed", size=400, overlap=80)
check("チャンク数 fixed(400/80)", len(chunks), 673)

index = LexicalIndex().build(chunks)
rep = evaluate(index, queries, qrels_all, k=10, label="bm25 / fixed")
print(f"\n{rep.summary()}")
check("回答可能クエリ数", int(rep.macro["n_queries"]), 110)
check("Recall@10", round(rep.macro["recall"], 3), 0.763, 0.02)
check("nDCG@10", round(rep.macro["ndcg"], 3), 0.713, 0.02)
check("MRR", round(rep.macro["mrr"], 3), 0.765, 0.02)
check("P@10", round(rep.macro["precision"], 3), 0.538, 0.02)

# 略語クエリは語彙一致では引けない（本書の出発点となる事実）
check("略語クエリの Recall@10（低いことを確認）",
      round(rep.by_type["abbrev"]["recall"], 3), 0.182, 0.03)
check("キーワードクエリの Recall@10（高いことを確認）",
      round(rep.by_type["keyword"]["recall"], 3), 0.967, 0.03)

# --- 小さな評価セット（手計算の答え合わせ）----------------------------------
import my_metrics  # noqa: E402
from toy_runs import QIDS, QRELS, QUERIES, RUNS_A, RUNS_B, ToyRetriever  # noqa: E402

toy_a = evaluate(ToyRetriever(RUNS_A), QUERIES, QRELS, k=5, label="手法A")
toy_b = evaluate(ToyRetriever(RUNS_B), QUERIES, QRELS, k=5, label="手法B")
check("toy 手法A Recall@5", round(toy_a.macro["recall"], 3), 0.700, 1e-9)
check("toy 手法A P@5", round(toy_a.macro["precision"], 3), 0.560, 1e-9)
check("toy 手法A MRR", round(toy_a.macro["mrr"], 3), 0.717, 1e-9)
check("toy 手法A nDCG@5", round(toy_a.macro["ndcg"], 3), 0.531, 1e-9)
check("toy 手法B Recall@5", round(toy_b.macro["recall"], 3), 0.475, 1e-9)
check("toy 手法B P@5", round(toy_b.macro["precision"], 3), 0.633, 1e-9)
check("toy 手法B MRR", round(toy_b.macro["mrr"], 3), 0.833, 1e-9)
check("toy 手法B nDCG@5", round(toy_b.macro["ndcg"], 3), 0.580, 1e-9)
check_true("Recall は A が上・nDCG は B が上（平均だけ見ると逆の結論になる）",
           toy_a.macro["recall"] > toy_b.macro["recall"]
           and toy_a.macro["ndcg"] < toy_b.macro["ndcg"])

agree = True
for runs in (RUNS_A, RUNS_B):
    retriever = ToyRetriever(runs)
    for qid in QIDS:
        hs, qr = retriever.search(qid, k=5), QRELS[qid]
        agree = agree and (
            abs(my_metrics.recall_at_k(hs, qr, 5) - recall_at_k(hs, qr, 5)) < 1e-12
            and abs(my_metrics.precision_at_k(hs, qr, 5) - precision_at_k(hs, qr, 5)) < 1e-12
            and abs(my_metrics.mrr(hs, qr) - mrr(hs, qr)) < 1e-12
            and abs(my_metrics.ndcg_at_k(hs, qr, 5) - ndcg_at_k(hs, qr, 5)) < 1e-12
        )
check_true("自作の my_metrics が ragkit.eval と全クエリで一致する", agree)

# --- k を変えたときの振る舞い -----------------------------------------------
answerable = [q for q in queries
              if any(g >= 1 for g in qrels_all.get(q.query_id, {}).values())]
check("回答可能クエリの数", len(answerable), 110)

mono_ok = True
sum5 = sum10 = sum20 = 0.0
for q in answerable:
    qr = qrels_all[q.query_id]
    hs = index.search(q.text, k=20)
    r5, r10, r20 = (recall_at_k(hs, qr, 5), recall_at_k(hs, qr, 10),
                    recall_at_k(hs, qr, 20))
    mono_ok = mono_ok and (r5 <= r10 <= r20)
    sum5, sum10, sum20 = sum5 + r5, sum10 + r10, sum20 + r20
check_true("Recall@k は k を増やしても下がらない（全クエリで成立）", mono_ok)
check_true("平均でも Recall@5 <= Recall@10 <= Recall@20", sum5 <= sum10 <= sum20)

# 検索の k と指標の k は別物：広く取ってから測っても Recall は下がらない
wider_ok = True
for q in answerable[:30]:
    qr = qrels_all[q.query_id]
    narrow = recall_at_k(index.search(q.text, k=10), qr, 10)
    wide = recall_at_k(index.search(q.text, k=50), qr, 10)
    wider_ok = wider_ok and (wide >= narrow)
check_true("検索件数を広げても指標@10 が下がらない（k の二重性）", wider_ok)

# --- 回答不能クエリを混ぜると平均が歪む -------------------------------------
rep_all = evaluate(index, queries, qrels_all, k=10,
                   label="bm25 / fixed（回答不能を含む）", skip_unanswerable=False)
check("回答不能を含めたクエリ数", int(rep_all.macro["n_queries"]), 120)
check_true("回答不能クエリを混ぜると平均 Recall が下がる",
           rep_all.macro["recall"] < rep.macro["recall"])

# --- 再現性：同点の決着が入力順に依存しないこと -----------------------------
tie_chunks = [
    Chunk("Z-0002#001", "Z-0002", "有給休暇の申請は3営業日前までに行う", 1, {}),
    Chunk("Z-0001#001", "Z-0001", "有給休暇の申請は3営業日前までに行う", 1, {}),
    Chunk("Z-0003#001", "Z-0003", "経費精算の締切は月末である", 1, {}),
]
tie_hits = LexicalIndex().build(tie_chunks).search("有給休暇の申請", k=3)
check("同点は chunk_id の昇順で決着する",
      [x.chunk_id for x in tie_hits[:2]], ["Z-0001#001", "Z-0002#001"])

# --- 条件を変えると指標が逆に動く（この章の中心データ）----------------------
chunks_h = chunk_all(docs, "heading", max_chars=600)
check("チャンク数 heading(600)", len(chunks_h), 2004)
index_h = LexicalIndex().build(chunks_h)
rep_h = evaluate(index_h, queries, qrels_all, k=10, label="bm25 / heading")
print(f"\n{rep_h.summary()}")
check("heading の Recall@10", round(rep_h.macro["recall"], 3), 0.668, 0.02)
check("heading の nDCG@10", round(rep_h.macro["ndcg"], 3), 0.722, 0.02)
check("heading の MRR", round(rep_h.macro["mrr"], 3), 0.815, 0.02)
check("heading の P@10", round(rep_h.macro["precision"], 3), 0.629, 0.02)
check_true("Recall は heading の方が低い", rep_h.macro["recall"] < rep.macro["recall"])
check_true("nDCG は heading の方が高い", rep_h.macro["ndcg"] > rep.macro["ndcg"])
check_true("MRR も P@10 も heading の方が高い",
           rep_h.macro["mrr"] > rep.macro["mrr"]
           and rep_h.macro["precision"] > rep.macro["precision"])

from win_loss import tally  # noqa: E402

tallied = tally(rep, rep_h, "recall")
check("勝ち負けの合計は回答可能クエリ数に一致する",
      tallied["a_win"] + tallied["b_win"] + tallied["tie"], 110)

# --- サンプル数の直観（互角の2手法をコイン投げで比べたときの勝敗）-----------
p10 = sum(math.comb(10, i) for i in range(7, 11)) / 2 ** 10
p20 = sum(math.comb(20, i) for i in range(15, 21)) / 2 ** 20
check("互角でも10クエリ中7勝以上する確率", round(p10, 6), 0.171875, 1e-12)
check("互角でも20クエリ中15勝以上する確率", round(p20, 6), 0.020695, 1e-12)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション2の検証はすべて成功しました。")
