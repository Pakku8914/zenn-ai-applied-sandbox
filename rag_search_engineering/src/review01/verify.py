#!/usr/bin/env python3
"""横断復習01（セッション2〜5）の自己検証。

  1. 指標の定義（Recall / Precision / MRR / nDCG）が手計算と一致すること
  2. 畳み込みが P@k の分母を縮めること（heading の高い P@10 の正体）
  3. BM25 × fixed / heading の実測値が本文の数値と一致し、指標が逆転していること
  4. 前処理で `#` を落とすと chunk_heading が chunk_sentence に化けること
  5. 文字bi-gramで拾える略語／拾えない略語の予測が当たること、同義語展開が効くこと
  6. BM25 の k1 と b が何を制御しているか（k1=0 で回数が効かない・b=0 で長さが効かない）
  7. 失敗が「到達不足」と「順位不足」に正しく分解されること

埋め込みモデルを使わないので3分程度で終わる。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_lab import (  # noqa: E402
    SYNONYMS, SynonymRetriever, expand_query, expand_query_naive, failure_split,
    mean_folded_docs, print_split, shares_bigram, strip_docs, win_loss, zero_term_docs,
)

from ragkit.chunk import chunk_all, chunk_heading, chunk_sentence  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate, mrr, ndcg_at_k, precision_at_k, recall_at_k  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk, Hit  # noqa: E402

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    shown = f"{got:.3f}" if isinstance(want, float) else got
    print(f"[{'OK' if ok else 'NG'}] {label}: got={shown} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


docs = load_docs()
queries = load_queries()
qrels = load_qrels()
docs_by_id = {d.doc_id: d for d in docs}

# ---------------------------------------------------------------------------
# 1. 指標の定義（手計算との突き合わせ）— セッション2
# ---------------------------------------------------------------------------
print("--- 1. 指標の定義 ---")

TOY_QRELS = {"D1": 2, "D2": 2, "D3": 1, "D4": 1, "D5": 1}


def toy_hits(doc_ids: list[str]) -> list[Hit]:
    """順位だけを持つダミーのヒット列（スコアは順位から作る）。"""
    return [Hit(f"{d}#{i:03d}", d, 1.0 / i, "", {}) for i, d in enumerate(doc_ids, start=1)]


# 走査は広いが上位が弱い（Recall は高く MRR は低い）
run_wide = toy_hits(["X1", "X2", "D1", "X3", "D2", "X4", "D3", "X5", "D4", "X6"])
# 上位は強いが取りこぼす（Recall は低く MRR は高い）
run_sharp = toy_hits(["D1", "D2", "X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"])

check("Recall@10 走査型", recall_at_k(run_wide, TOY_QRELS, 10), 0.8, 0.001)
check("P@10 走査型", precision_at_k(run_wide, TOY_QRELS, 10), 0.4, 0.001)
check("MRR 走査型", mrr(run_wide, TOY_QRELS), 0.333, 0.001)
check("nDCG@10 走査型", ndcg_at_k(run_wide, TOY_QRELS, 10), 0.526, 0.001)

check("Recall@10 一点型", recall_at_k(run_sharp, TOY_QRELS, 10), 0.4, 0.001)
check("P@10 一点型", precision_at_k(run_sharp, TOY_QRELS, 10), 0.2, 0.001)
check("MRR 一点型", mrr(run_sharp, TOY_QRELS), 1.0, 0.001)
check("nDCG@10 一点型", ndcg_at_k(run_sharp, TOY_QRELS, 10), 0.712, 0.001)

check_true("Recall は走査型が上・MRR と nDCG は一点型が上（1指標では順位が付かない）",
           recall_at_k(run_wide, TOY_QRELS, 10) > recall_at_k(run_sharp, TOY_QRELS, 10)
           and mrr(run_sharp, TOY_QRELS) > mrr(run_wide, TOY_QRELS)
           and ndcg_at_k(run_sharp, TOY_QRELS, 10) > ndcg_at_k(run_wide, TOY_QRELS, 10))

# ---------------------------------------------------------------------------
# 2. 畳み込みと P@k の分母 — セッション2 × セッション4
# ---------------------------------------------------------------------------
print("\n--- 2. 畳み込みと P@k の分母 ---")

# 上位10件が3文書に畳み込まれるケース（細かく切った方式で起きる）
run_folded = toy_hits(["D1", "D1", "D2", "D1", "X1", "D2", "D1", "X1", "D2", "X1"])
check("畳み込み後の文書数", len({h.doc_id for h in run_folded}), 3)
check("Recall@10 畳み込み型", recall_at_k(run_folded, TOY_QRELS, 10), 0.4, 0.001)
check("MRR 畳み込み型", mrr(run_folded, TOY_QRELS), 1.0, 0.001)
check("P@10 畳み込み型（分母が10ではなく3になる）",
      precision_at_k(run_folded, TOY_QRELS, 10), 0.667, 0.001)
check_true("Recall が同じでも P@10 は畳み込み型のほうが高い（分母が縮むだけで上がる）",
           recall_at_k(run_folded, TOY_QRELS, 10) == recall_at_k(run_sharp, TOY_QRELS, 10)
           and precision_at_k(run_folded, TOY_QRELS, 10)
           > precision_at_k(run_sharp, TOY_QRELS, 10))

# ---------------------------------------------------------------------------
# 3. BM25 × チャンク方式の実測（本文の数値の出典）— セッション4 × セッション2
# ---------------------------------------------------------------------------
print("\n--- 3. BM25 × チャンク方式 ---")

chunks_fixed = chunk_all(docs, "fixed", size=400, overlap=80)
chunks_heading = chunk_all(docs, "heading", max_chars=600)
check("チャンク数 fixed(400/80)", len(chunks_fixed), 673)
check("チャンク数 heading(600)", len(chunks_heading), 2004)

idx_fixed = LexicalIndex().build(chunks_fixed)
idx_heading = LexicalIndex().build(chunks_heading)
rep_fixed = evaluate(idx_fixed, queries, qrels, k=10, label="bm25 / fixed")
rep_heading = evaluate(idx_heading, queries, qrels, k=10, label="bm25 / heading")
print(rep_fixed.summary())
print(rep_heading.summary())

check("Recall@10 bm25 / fixed", rep_fixed.macro["recall"], 0.763, 0.02)
check("nDCG@10 bm25 / fixed", rep_fixed.macro["ndcg"], 0.713, 0.02)
check("MRR bm25 / fixed", rep_fixed.macro["mrr"], 0.765, 0.02)
check("P@10 bm25 / fixed", rep_fixed.macro["precision"], 0.538, 0.02)
check("Recall@10 bm25 / heading", rep_heading.macro["recall"], 0.668, 0.02)
check("nDCG@10 bm25 / heading", rep_heading.macro["ndcg"], 0.722, 0.02)
check("MRR bm25 / heading", rep_heading.macro["mrr"], 0.815, 0.02)
check("P@10 bm25 / heading", rep_heading.macro["precision"], 0.629, 0.02)
check("abbrev の Recall@10 bm25 / fixed", rep_fixed.by_type["abbrev"]["recall"], 0.182, 0.03)
check("multi_condition の Recall@10 bm25 / heading",
      rep_heading.by_type["multi_condition"]["recall"], 0.477, 0.03)

check_true("heading は Recall だけが低い（他の3指標は fixed より高い）",
           rep_heading.macro["recall"] < rep_fixed.macro["recall"]
           and rep_heading.macro["ndcg"] > rep_fixed.macro["ndcg"]
           and rep_heading.macro["mrr"] > rep_fixed.macro["mrr"]
           and rep_heading.macro["precision"] > rep_fixed.macro["precision"])

folded_fixed = mean_folded_docs(idx_fixed, queries, qrels)
folded_heading = mean_folded_docs(idx_heading, queries, qrels)
check_true("heading は上位10件がより少ない文書に畳み込まれる（P@10 の分母が縮む）",
           folded_heading < folded_fixed,
           f"heading {folded_heading:.2f} < fixed {folded_fixed:.2f}")

tally = win_loss(rep_fixed, rep_heading, "recall")
print(f"クエリ単位の勝敗（fixed 対 heading・Recall@10）: {tally}")
check_true("平均では fixed の勝ちだが、heading が勝つクエリも存在する",
           tally["win"] > 0 and tally["loss"] > 0)

# ---------------------------------------------------------------------------
# 4. 前処理の事故 — セッション3 × セッション4
# ---------------------------------------------------------------------------
print("\n--- 4. 前処理の事故 ---")

HEADING_RE = re.compile(r"^#{1,4}\s*(.+)$", re.MULTILINE)
check("見出し行を持つ文書数（前処理まえ）",
      sum(1 for d in docs if HEADING_RE.search(d.body)), 301)

stripped = strip_docs(docs)
check("見出し行を持つ文書数（`#` を落としたあと）",
      sum(1 for d in stripped if HEADING_RE.search(d.body)), 0)

sh = [c for d in stripped for c in chunk_heading(d, 600)]
ss = [c for d in stripped for c in chunk_sentence(d, 600)]
check_true("前処理後の chunk_heading と chunk_sentence のチャンク数が一致", len(sh) == len(ss))
check_true("チャンクIDと本文まで完全一致する（heading が sentence に化けている）",
           [(c.chunk_id, c.text) for c in sh] == [(c.chunk_id, c.text) for c in ss])
print(f"heading(600) のチャンク数 {len(chunks_heading)} → {len(sh)}")
check_true("チャンク数が heading(600) の 2,004 から大きく減る", len(sh) < 1000)

idx_stripped = LexicalIndex().build(sh)
rep_stripped = evaluate(idx_stripped, queries, qrels, k=10, label="bm25 / heading（前処理後）")
print(rep_stripped.summary())
check_true("索引としては壊れていない（Recall@10 が 0.3 以上ある）",
           rep_stripped.macro["recall"] > 0.3)
check_true("4指標すべてが heading(600) から動く（チャンク方式は1文字も変えていないのに）",
           all(abs(rep_stripped.macro[m] - rep_heading.macro[m]) > 1e-6
               for m in ("recall", "ndcg", "mrr", "precision")))

# ---------------------------------------------------------------------------
# 5. 略語への対策 — セッション3 × セッション5 × セッション2
# ---------------------------------------------------------------------------
print("\n--- 5. 略語への対策 ---")

# 文字bi-gramに切り替えたときに正式名称へ当たる略語（測る前に紙の上で決まる）
SHARED = {"スマホ", "パス", "二要素認証", "2段階認証", "不審メール", "クラウドサービス"}
for key, canon in SYNONYMS.items():
    check(f"bi-gram を共有する? {key} → {canon}", shares_bigram(key, canon), key in SHARED)

idx_bigram = LexicalIndex(mode="bigram").build(chunks_fixed)
check_true("bigram の語彙数は morph より多い",
           len(idx_bigram.postings) > len(idx_fixed.postings),
           f"{len(idx_bigram.postings)} > {len(idx_fixed.postings)}")
check_true("bigram の延べポスティング数も morph より多い（索引が太る）",
           sum(len(v) for v in idx_bigram.postings.values())
           > sum(len(v) for v in idx_fixed.postings.values()))
rep_bigram = evaluate(idx_bigram, queries, qrels, k=10, label="bm25 / fixed / bigram")
print(rep_bigram.summary())
print(f"  abbrev の Recall@10: {rep_bigram.by_type['abbrev']['recall']:.3f}")
check_true("bigram の索引も検索としては成立している（Recall@10 が 0.2 以上）",
           rep_bigram.macro["recall"] > 0.2)

# 同義語辞書のふるまい
check("素朴な置換は部分文字列に当たって壊れる",
      expand_query_naive("パスワードの再設定"), "パスワードワードの再設定")
check("素朴な置換は全角の略語に当たらない",
      expand_query_naive("ＭＦＡの手続きを知りたい"), "ＭＦＡの手続きを知りたい")
check("正規化してから照合すれば全角でも当たる",
      expand_query("ＭＦＡの手続きを知りたい"), "ＭＦＡの手続きを知りたい 多要素認証")
check("正式名称がすでに入っているクエリは触らない",
      expand_query("パスワードの再設定"), "パスワードの再設定")
check("略語クエリには正式名称が足される",
      expand_query("年休の手続きを知りたい"), "年休の手続きを知りたい 有給休暇")

fired = [q for q in queries if expand_query(q.text) != q.text]
check("展開が発火したクエリ数", len(fired), 20)
check("発火したのは略語クエリだけ", sorted({q.type for q in fired}), ["abbrev"])

rep_syn = evaluate(SynonymRetriever(idx_fixed), queries, qrels, k=10,
                   label="bm25 / fixed + 同義語")
print(rep_syn.summary())
print(f"  abbrev の Recall@10: {rep_syn.by_type['abbrev']['recall']:.3f}"
      f"（展開なし {rep_fixed.by_type['abbrev']['recall']:.3f}）")
check_true("略語クエリの Recall@10 が展開なしより上がる",
           rep_syn.by_type["abbrev"]["recall"] > rep_fixed.by_type["abbrev"]["recall"])
check_true("略語クエリの Recall@10 が 0.40 を超える",
           rep_syn.by_type["abbrev"]["recall"] >= 0.40)
for qtype in ("keyword", "multi_condition", "natural", "temporal"):
    check_true(f"{qtype} の指標は1つも動かない（展開が発火しないため）",
               rep_syn.by_type[qtype] == rep_fixed.by_type[qtype])
check_true("全体の Recall@10 も上がる",
           rep_syn.macro["recall"] > rep_fixed.macro["recall"] + 0.02)

# ---------------------------------------------------------------------------
# 6. BM25 の k1 と b — セッション5
# ---------------------------------------------------------------------------
print("\n--- 6. BM25 の k1 と b ---")

toy_many = Chunk("T1#001", "T1", "有給休暇 有給休暇 有給休暇", 1)
toy_once = Chunk("T2#001", "T2", "有給休暇", 1)
idx_k1 = LexicalIndex(k1=1.2, b=0.75).build([toy_many, toy_once])
score = {h.doc_id: h.score for h in idx_k1.search("有給休暇", k=10)}
check_true("k1=1.2 では出現回数の多いチャンクが上に来る", score["T1"] > score["T2"])
idx_k1.k1 = 0.0
score0 = {h.doc_id: h.score for h in idx_k1.search("有給休暇", k=10)}
check_true("k1=0 では出現回数が効かない（BM25 が純粋な IDF の和になる）",
           abs(score0["T1"] - score0["T2"]) < 1e-12)

FILLER = ("会議室 駐車場 郵便物 座席 備品 手当 精算 承認 記録 保管 "
          "廃棄 通知 添付 書類 期限 窓口 担当 部門 端末 台帳")
toy_short = Chunk("S1#001", "S1", "有給休暇の申請", 1)
toy_long = Chunk("L1#001", "L1", f"有給休暇の申請 {FILLER}", 1)
idx_b = LexicalIndex(k1=1.2, b=0.75).build([toy_short, toy_long])
score_b = {h.doc_id: h.score for h in idx_b.search("有給休暇", k=10)}
check_true("b=0.75 では短いチャンクが有利（文書長で割るため）", score_b["S1"] > score_b["L1"])
idx_b.b = 0.0
score_b0 = {h.doc_id: h.score for h in idx_b.search("有給休暇", k=10)}
check_true("b=0 では長さの差が消える（同じ tf なら同じスコア）",
           abs(score_b0["S1"] - score_b0["L1"]) < 1e-12)

# 実コーパスでも b を外すと結果が変わる（値そのものは各自の実行結果で確認する）
idx_fixed.b = 0.0
rep_b0 = evaluate(idx_fixed, queries, qrels, k=10, label="bm25 / fixed (b=0)")
idx_fixed.b = 0.75  # 以降の測定に影響させないため必ず戻す
print(rep_b0.summary())
check_true("実コーパスでも b=0 は b=0.75 と違う結果になる",
           abs(rep_b0.macro["recall"] - rep_fixed.macro["recall"]) > 1e-6)
check_true("b を戻したあとの Recall@10 が元の値に戻る（共有した索引を汚していない）",
           abs(evaluate(idx_fixed, queries, qrels, k=10).macro["recall"]
               - rep_fixed.macro["recall"]) < 1e-9)

# ---------------------------------------------------------------------------
# 7. 失敗の分解 — セッション2 × セッション5
# ---------------------------------------------------------------------------
print("\n--- 7. 失敗の分解 ---")

split_base = failure_split(idx_fixed, queries, qrels, k=10, pool=100)
split_syn = failure_split(SynonymRetriever(idx_fixed), queries, qrels, k=10, pool=100)
print_split("bm25 / fixed", split_base)
print_split("bm25 / fixed + 同義語", split_syn)

for qtype in ("abbrev", "multi_condition", "ALL"):
    row = split_base[qtype]
    check_true(f"{qtype}: Recall@10 ＋ 順位不足 ＋ 到達不足 = 1",
               abs(row["recall"] + row["rank_loss"] + row["reach_loss"] - 1.0) < 1e-9)
check_true("略語の失敗は到達不足が大きい（候補にすら入っていない）",
           split_base["abbrev"]["reach_loss"] > 0.2)
check_true("略語には順位不足もある（候補には居るのに上位10件に来ない）",
           split_base["abbrev"]["rank_loss"] > 0.0)
check_true("同義語展開は到達不足を減らす（順位ではなく語彙の対策だから）",
           split_syn["abbrev"]["reach_loss"] < split_base["abbrev"]["reach_loss"])

zero = zero_term_docs("年休の手続きを知りたい",
                      [d for d, g in qrels["Q-067"].items() if g >= 1], docs_by_id)
check_true("Q-067 の適合文書には、クエリの語を1つも含まないものが2件以上ある",
           len(zero) >= 2, f"{len(zero)} 件: {zero}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n横断復習01の検証はすべて成功しました。")
