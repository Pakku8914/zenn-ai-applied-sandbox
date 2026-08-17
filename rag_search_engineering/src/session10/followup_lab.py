#!/usr/bin/env python3
"""会話の続きの発話を、単独で検索できるクエリに書き換える（自立化）。

    python src/session10/followup_lab.py

APIキーは不要（StubClient が決定的に書き換える）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import (  # noqa: E402
    CountingClient,
    carry_over,
    make_followup_client,
    needs_context,
    resolve_followup,
)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels  # noqa: E402
from ragkit.eval import recall_at_k  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

# (会話履歴, 続きの発話)
CONVERSATIONS: list[tuple[list[str], str]] = [
    (["有給休暇の申請期限を教えてください"], "それは何日前まで？"),
    (["会議室の予約方法を教えてください"], "その上限は？"),
    (["多要素認証の登録期限を教えてください"], "パスワードの再設定は？"),
    (["駐車場の月額利用料を教えてください"], "それは何日前まで？"),
]
TOPIC = "有給休暇"
BASE_QUERY_ID = "Q-001"  # 1つめの会話のもとになった質問


def main() -> None:
    docs, qrels = load_docs(), load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))
    client = CountingClient(make_followup_client())

    print("=== 1. 自立化の3通り ===")
    for history, text in CONVERSATIONS:
        print(f"履歴: {history[-1]}")
        print(f"発話: {text}")
        print(f"  指示語あり : {needs_context(text)}")
        print(f"  ルール版   : {carry_over(history, text)}")
        print(f"  Stub 版    : {resolve_followup(history, text, client)}")

    print(f"\nLLM 呼び出し: {client.calls} 回 / {len(CONVERSATIONS)} 発話"
          "（指示語が無い発話では呼んでいない）")

    print("\n=== 2. 自立化すると何が変わるか ===")
    history, text = CONVERSATIONS[0]
    qr = qrels[BASE_QUERY_ID]
    variants = {
        "raw": text,
        "carry_over": carry_over(history, text),
        "stub": resolve_followup(history, text, client),
    }
    print(f"{'variant':<14}{'topic_hits':>12}{'recall@10':>12}  query")
    for label, q in variants.items():
        hits = index.search(q, k=10)
        topic_hits = sum(1 for h in hits if TOPIC in h.text)
        print(f"{label:<14}{topic_hits:>12}{recall_at_k(hits, qr, 10):>12.3f}  {q}")
    print(f"  topic_hits: 上位10件のうち「{TOPIC}」を含むチャンクの数")
    print(f"  recall@10 : {BASE_QUERY_ID}（もとの質問）の判定データで測った値")


if __name__ == "__main__":
    main()
