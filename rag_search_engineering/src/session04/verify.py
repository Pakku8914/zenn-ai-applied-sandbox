#!/usr/bin/env python3
"""セッション4の自己検証。

  1. 4方式のチャンク統計が本文の数値と一致すること
  2. 親子チャンクの不変条件（子は必ず親に含まれる／子は fixed(200/0) と同一）
  3. 見出し分割の既知の弱点（コードブロック内のコメントを見出しと誤検出する）
  4. 後処理ユーティリティ（重なりの除去・畳み込み・予算）の振る舞い
  5. BM25 での4方式の精度が本文の数値と一致すること

埋め込みモデルを使わないので1分程度で終わる。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunk_lab import (  # noqa: E402
    build_context, chunk_heading_merged, fixed_chunks, join_without_overlap,
    mean_folded_docs, merge_adjacent, overlap_len,
)
from ragkit.chunk import chunk_all, chunk_fixed, chunk_heading  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk, Hit  # noqa: E402

failures: list[str] = []


def check(label: str, got, want, tol: float = 0.0) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(f"[{'OK' if ok else 'NG'}] {label}: got={got} want={want}")
    if not ok:
        failures.append(label)


def check_true(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'NG'}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


docs = load_docs()
queries = load_queries()
qrels = load_qrels()

# --- 1. チャンク統計（tools/chunk_stats.py と同じ計算）----------------------
print("--- 1. チャンク統計 ---")
base_chars = sum(len(d.full_text) for d in docs)
check("文書数", len(docs), 301)
check("元テキスト総文字数", base_chars, 174062)

STATS = [
    ("fixed(400/80)", "fixed", dict(size=400, overlap=80), 673, 301, 400),
    ("fixed(800/160)", "fixed", dict(size=800, overlap=160), 373, 497, 800),
    ("fixed(200/0)", "fixed", dict(size=200, overlap=0), 1007, 172, 200),
    ("sentence(400)", "sentence", dict(max_chars=400), 628, 276, 400),
    ("heading(600)", "heading", dict(max_chars=600), 2004, 101, 600),
    ("parent_window(200/600)", "parent_window", dict(child=200, window=600), 1007, 172, 200),
]
for label, method, params, want_n, want_mean, limit in STATS:
    chunks = chunk_all(docs, method, **params)
    lengths = [len(c.text) for c in chunks]
    mean_length = statistics.mean(lengths)
    check(f"チャンク数 {label}", len(chunks), want_n)
    check_true(f"平均長 {label}", abs(mean_length - want_mean) <= 1.5,
               f"{mean_length:.1f} ≒ {want_mean}")
    check_true(f"最大長 {label} が {limit} 以下", max(lengths) <= limit, f"max={max(lengths)}")

# 自作の最小実装が ragkit と同じ切り方になること
mine = [p.strip() for p in fixed_chunks(docs[0].full_text, 400, 80) if p.strip()]
check_true("自作の固定長分割が ragkit.chunk.chunk_fixed と一致する",
           mine == [c.text for c in chunk_fixed(docs[0], 400, 80)])

# --- 2. 親子チャンクの不変条件 ----------------------------------------------
print("\n--- 2. 親子チャンク ---")
parents = chunk_all(docs, "parent_window", child=200, window=600)
plain200 = chunk_all(docs, "fixed", size=200, overlap=0)
check_true("parent_window の子は fixed(200/0) と同一（BM25 の索引は同じものになる）",
           [(c.chunk_id, c.text) for c in parents] == [(c.chunk_id, c.text) for c in plain200])
check("子が親に含まれないチャンク数",
      len([c for c in parents if c.text not in c.meta["parent_text"]]), 0)
check("親が子より短いチャンク数",
      len([c for c in parents if len(c.meta["parent_text"]) < len(c.text)]), 0)

# --- 3. 見出し分割の既知の弱点 ----------------------------------------------
print("\n--- 3. 見出し分割の弱点 ---")
code_doc = next(d for d in docs if "```python" in d.body)
misdetected = [c for c in chunk_heading(code_doc, 600)
               if c.text.startswith(f"{code_doc.title}\n# ")]
check_true("コードブロック内のコメント行を見出しと誤検出する（既知の弱点）",
           len(misdetected) >= 1, f"{code_doc.doc_id} で {len(misdetected)} 件")

# --- 4. 後処理ユーティリティ -------------------------------------------------
print("\n--- 4. 後処理 ---")
check("重なりの検出", overlap_len("有給休暇の申請は", "の申請は3営業日前まで"), 4)
check("重なりを1回だけ残して連結",
      join_without_overlap("有給休暇の申請は", "の申請は3営業日前まで"), "有給休暇の申請は3営業日前まで")
check("重なりが無ければそのまま連結", join_without_overlap("あいう", "えお"), "あいうえお")

sample = docs[0]
sample_chunks = chunk_fixed(sample, size=400, overlap=80)
sample_hits = [Hit(c.chunk_id, c.doc_id, 1.0 / (i + 1), c.text, c.meta)
               for i, c in enumerate(sample_chunks)]
naive_chars = sum(len(h.text) for h in sample_hits)
merged = merge_adjacent(sample_hits)
check("畳み込み後の Passage 数（1文書なので1件）", len(merged), 1)
check_true("オーバーラップぶんの重複が消えている", len(merged[0].text) < naive_chars,
           f"{len(merged[0].text)} < {naive_chars}")
check_true("畳み込んだ本文が先頭チャンクで始まる",
           merged[0].text.startswith(sample_chunks[0].text))
check_true("由来のチャンクIDを保持している",
           merged[0].chunk_ids == tuple(c.chunk_id for c in sample_chunks))

first_of_doc: dict[str, Chunk] = {}
for chunk in parents:
    first_of_doc.setdefault(chunk.doc_id, chunk)
parent_hits = [Hit(c.chunk_id, c.doc_id, 1.0 - i * 0.01, c.text, c.meta)
               for i, c in enumerate(list(first_of_doc.values())[:5])]
context = build_context(parent_hits, budget=1200, use_parent=True)
total_chars = sum(len(p.text) for p in context)
check_true("コンテキストが予算を超えない", total_chars <= 1200, f"{total_chars} <= 1200")
check("同じ文書を二重に入れていない", len({p.doc_id for p in context}), len(context))
child_of = {h.chunk_id: h.text for h in parent_hits}
check_true("親テキストを渡している（子を必ず含む）",
           all(child_of[p.chunk_ids[0]] in p.text for p in context))
check("予算50字なら先頭を切り詰めて1件だけ返す",
      [len(p.text) for p in build_context(parent_hits, budget=50, use_parent=True)], [50])

# --- 5. 見出し分割の改良版 ---------------------------------------------------
print("\n--- 5. 見出し分割の改良版 ---")
merged_chunks = [c for d in docs for c in chunk_heading_merged(d, max_chars=600, min_chars=200)]
merged_lengths = [len(c.text) for c in merged_chunks]
check_true("極小節の併合でチャンク数が減る", len(merged_chunks) < 2004,
           f"{len(merged_chunks)} < 2004")
check_true("併合で平均長が伸びる", statistics.mean(merged_lengths) > 101,
           f"{statistics.mean(merged_lengths):.1f} > 101")
check_true("併合後も上限を超えない", max(merged_lengths) <= 600, f"max={max(merged_lengths)}")
report_merged = evaluate(LexicalIndex().build(merged_chunks), queries, qrels, k=10,
                         label="bm25 / heading_merged")
print(report_merged.summary())
check_true("併合版の Recall@10 が 0.5 以上（索引として壊れていない）",
           report_merged.macro["recall"] >= 0.5, f"{report_merged.macro['recall']:.3f}")

# --- 6. BM25 での4方式比較（本文の数値の出典）--------------------------------
CHUNK_PARAMS = {
    "fixed": dict(size=400, overlap=80),
    "sentence": dict(max_chars=400),
    "heading": dict(max_chars=600),
    "parent_window": dict(child=200, window=600),
}
EXPECTED = {
    "fixed": dict(recall=0.763, ndcg=0.713, mrr=0.765, precision=0.538),
    "sentence": dict(recall=0.748, ndcg=0.719, mrr=0.777, precision=0.544),
    "heading": dict(recall=0.668, ndcg=0.722, mrr=0.815, precision=0.629),
    "parent_window": dict(recall=0.781, ndcg=0.694, mrr=0.830, precision=0.548),
}
indexes = {}
reports = {}
for method, params in CHUNK_PARAMS.items():
    indexes[method] = LexicalIndex().build(chunk_all(docs, method, **params))
    reports[method] = evaluate(indexes[method], queries, qrels, k=10, label=f"bm25 / {method}")

print("\n--- 6. 畳み込み後の文書数 ---")
folded_fixed = mean_folded_docs(indexes["fixed"], queries, qrels)
folded_heading = mean_folded_docs(indexes["heading"], queries, qrels)
check_true("heading は上位10件がより少ない文書に畳み込まれる（P@10 の分母が縮む）",
           folded_heading < folded_fixed,
           f"heading {folded_heading:.1f} < fixed {folded_fixed:.1f}")

print("\n--- 7. BM25 での4方式比較 ---")
for method, want in EXPECTED.items():
    report = reports[method]
    print(report.summary())
    check(f"Recall@10 bm25 / {method}", round(report.macro["recall"], 3), want["recall"], 0.02)
    check(f"nDCG@10 bm25 / {method}", round(report.macro["ndcg"], 3), want["ndcg"], 0.02)
    check(f"MRR bm25 / {method}", round(report.macro["mrr"], 3), want["mrr"], 0.02)
    check(f"P@10 bm25 / {method}", round(report.macro["precision"], 3), want["precision"], 0.02)

check("abbrev の Recall@10 bm25 / fixed",
      round(reports["fixed"].by_type["abbrev"]["recall"], 3), 0.182, 0.03)
check("multi_condition の Recall@10 bm25 / heading",
      round(reports["heading"].by_type["multi_condition"]["recall"], 3), 0.477, 0.03)
check("temporal の Recall@10 bm25 / parent_window",
      round(reports["parent_window"].by_type["temporal"]["recall"], 3), 0.983, 0.03)
check_true("複数条件クエリでは heading が fixed に勝つ",
           reports["heading"].by_type["multi_condition"]["recall"]
           > reports["fixed"].by_type["multi_condition"]["recall"])

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション4の検証はすべて成功しました。")
