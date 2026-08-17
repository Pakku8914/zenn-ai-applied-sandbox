#!/usr/bin/env python3
"""同義語辞書を変更したときの回帰テスト。

  - 発火するクエリの一覧（型別の件数つき）
  - 対象外の型の指標が1つも動いていないこと
  - 辞書のキーと正式名称がコーパス側に実在すること
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_lab import SYNONYMS, SynonymRetriever, expand_query  # noqa: E402

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.tokenize_ja import normalize  # noqa: E402

TARGET_TYPES = {"abbrev"}          # この辞書が面倒を見る型
GUARD_TYPES = ("keyword", "natural", "multi_condition", "temporal")

docs = load_docs()
queries = load_queries()
qrels = load_qrels()
index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))

failed: list[str] = []

# ① 辞書の語がコーパスに実在するかを確かめる
corpus_text = normalize(" ".join(d.full_text for d in docs))
for key, canon in SYNONYMS.items():
    if normalize(canon) not in corpus_text:
        failed.append(f"正式名称がコーパスに無い: {key} → {canon}")
    if normalize(key) in corpus_text:
        print(f"[注意] 略語が本文にも出現する: {key}（辞書が不要な可能性）")

# ② どのクエリで発火するかを一覧にする
fired: dict[str, list[str]] = {}
for q in queries:
    if expand_query(q.text) != q.text:
        fired.setdefault(q.type, []).append(q.query_id)
for qtype, ids in sorted(fired.items()):
    print(f"発火 {qtype:<16} {len(ids):>3}件  {ids[:5]}{' ...' if len(ids) > 5 else ''}")
    if qtype not in TARGET_TYPES:
        failed.append(f"対象外の型で発火した: {qtype} ({len(ids)}件)")

# ③ 対象外の型の指標が1つも動いていないことを確認する
base = evaluate(index, queries, qrels, k=10, label="辞書なし")
after = evaluate(SynonymRetriever(index), queries, qrels, k=10, label="辞書あり")
for qtype in GUARD_TYPES:
    if base.by_type[qtype] != after.by_type[qtype]:
        failed.append(f"対象外の型の指標が動いた: {qtype}")

# ④ 対象の型が改善しているか
for qtype in sorted(TARGET_TYPES):
    delta = after.by_type[qtype]["recall"] - base.by_type[qtype]["recall"]
    print(f"{qtype} の Recall@10 の変化: {delta:+.3f}")
    if delta <= 0:
        failed.append(f"対象の型が改善していない: {qtype}")

if failed:
    print("\n回帰テスト失敗:")
    for line in failed:
        print(f"  - {line}")
    sys.exit(1)
print("\n回帰テストに合格しました。")
