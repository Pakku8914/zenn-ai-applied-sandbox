#!/usr/bin/env python3
"""合成カセット（fixtures）を生成する。

これは実 API の記録ではなく、決定的に組み立てた合成データである。
読者に課金を要求せずに「回答生成の後処理」を学べるようにするための仕組み。

出力:
  fixtures/answers_v1.json         正常系（引用あり・回答不能の判定あり）
  fixtures/answers_flawed_v1.json  異常系（引用なし・存在しない引用・回答不能なのに答える）

前提となる検索条件（カセットのキーはプロンプト全体のハッシュなので、ここを変えると
キーが変わる）: チャンク fixed(400/80) / BM25 / 上位5件
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import cache_key  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "fixtures"
TOP_K = 5
MAX_CHARS = 2000


def synth_answer(query, hits, qrels_for_query: dict[str, int]) -> dict:
    """正常系の合成応答。適合文書がコンテキストに入っているかで答えを変える。"""
    relevant_in_context = [h for h in hits if qrels_for_query.get(h.doc_id, 0) >= 2]
    if not relevant_in_context:
        payload = {"answerable": False,
                   "answer": "提供された参考文書には該当する記載が見つかりませんでした。"
                             "社内ポータルの担当窓口へお問い合わせください。",
                   "citations": []}
    else:
        top = relevant_in_context[0]
        title = top.meta.get("title", "")
        payload = {
            "answerable": True,
            "answer": f"「{title}」の記載に基づくと、{query.text.rstrip('。')}については"
                      f"次のとおりです。該当箇所を引用しています。詳細は担当窓口へ確認してください。",
            "citations": [h.chunk_id for h in relevant_in_context[:2]],
        }
    return payload


def synth_flawed(query, hits, qrels_for_query: dict[str, int], variant: int) -> dict:
    """異常系の合成応答。セッション11の後処理演習で検出させる3種。"""
    relevant = [h for h in hits if qrels_for_query.get(h.doc_id, 0) >= 2]
    if variant == 0:  # 引用が無い
        return {"answerable": True,
                "answer": "申請は所属部門の窓口を通じて行ってください。期限にご注意ください。",
                "citations": []}
    if variant == 1:  # 存在しない chunk_id を引用する
        return {"answerable": True,
                "answer": "規程に基づき、所定の期限までに申請してください。",
                "citations": ["DOC-9999#001"]}
    # 回答不能なのに答える
    return {"answerable": True,
            "answer": "担当部署に確認したところ、特に制限はないとのことです。",
            "citations": [relevant[0].chunk_id] if relevant else []}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=TOP_K)
    args = ap.parse_args()

    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    index = LexicalIndex().build(chunks)

    good: dict[str, dict] = {}
    flawed: dict[str, dict] = {}
    for i, q in enumerate(queries):
        hits = index.search(q.text, k=args.top_k)
        user = build_user_prompt(q.text, hits, max_chars=MAX_CHARS)
        key = cache_key(SYSTEM_PROMPT, user)
        qr = qrels.get(q.query_id, {})

        payload = synth_answer(q, hits, qr)
        text = json.dumps(payload, ensure_ascii=False)
        good[key] = {"text": text, "query_id": q.query_id,
                     "input_tokens": len(user) // 3, "output_tokens": len(text) // 3}

        bad = synth_flawed(q, hits, qr, i % 3)
        bad_text = json.dumps(bad, ensure_ascii=False)
        flawed[key] = {"text": bad_text, "query_id": q.query_id, "variant": i % 3,
                       "input_tokens": len(user) // 3, "output_tokens": len(bad_text) // 3}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "answers_v1.json").write_text(json.dumps(good, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    (OUT / "answers_flawed_v1.json").write_text(json.dumps(flawed, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    answerable = sum(1 for v in good.values() if '"answerable": true' in v["text"])
    print(f"fixtures/answers_v1.json        : {len(good)} 件（answerable={answerable}）")
    print(f"fixtures/answers_flawed_v1.json : {len(flawed)} 件")


if __name__ == "__main__":
    main()
