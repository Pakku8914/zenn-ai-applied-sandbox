#!/usr/bin/env python3
"""セッション11：合成カセットの応答を後処理で仕分ける。

  docker compose exec app python src/session11/postprocess_lab.py

APIキーは不要。fixtures/answers_v1.json（正常系）と
fixtures/answers_flawed_v1.json（異常系）を再生する。
どちらも tools/make_fixtures.py が固定シードで作った合成カセットであり、
実 API の記録ではない。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from answer_lab import (  # noqa: E402
    ABSTAINED,
    INVALID_CITATION,
    NO_CITATION,
    OK,
    guarded_answer,
    review_answer,
)
from ragkit.answer import answer_with_citations  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

docs, queries, qrels = load_docs(), load_queries(), load_qrels()
chunks = chunk_all(docs, "fixed", size=400, overlap=80)
index = LexicalIndex().build(chunks)
hits_by_query = {q.query_id: index.search(q.text, k=5) for q in queries}

good = FixtureClient("answers_v1")
flawed = FixtureClient("answers_flawed_v1")
answerable_q = [q for q in queries if any(g >= 2 for g in qrels.get(q.query_id, {}).values())]
unanswerable_q = [q for q in queries if q.type == "unanswerable"]


def verdicts_for(client, targets) -> Counter:
    counter: Counter = Counter()
    for q in targets:
        hits = hits_by_query[q.query_id]
        answer = answer_with_citations(client, q.text, hits)
        counter[review_answer(answer, hits).verdict] += 1
    return counter


print("=== 1. 正常系カセット（answers_v1）===")
ok_counter = verdicts_for(good, answerable_q[:20])
abs_counter = verdicts_for(good, unanswerable_q)
print(f"回答可能クエリ {len(answerable_q[:20])}件 : ok={ok_counter[OK]}")
print(f"回答不能クエリ {len(unanswerable_q)}件 : abstained={abs_counter[ABSTAINED]}")

print()
print("=== 2. 異常系カセット（answers_flawed_v1）・先頭30件 ===")
bad_counter = verdicts_for(flawed, queries[:30])
print(f"ok               : {bad_counter[OK]}")
print(f"no_citation      : {bad_counter[NO_CITATION]}")
print(f"invalid_citation : {bad_counter[INVALID_CITATION]}")

print()
print("=== 3. 回答不能クエリに異常系カセットを当てる ===")
dropped = 0
for q in unanswerable_q:
    hits = hits_by_query[q.query_id]
    answer, review = guarded_answer(flawed, q.text, hits)
    if not review.accepted:
        dropped += 1
print(f"落とした: {dropped} / {len(unanswerable_q)}（引用の検証だけで全部落ちる）")
