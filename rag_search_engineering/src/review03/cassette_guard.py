#!/usr/bin/env python3
"""合成カセットが何に依存しているかを目で見る（決定的に回る評価パイプラインの前提）。

合成カセットの鍵は **プロンプト全体の SHA-256** である。つまり検索条件を1つ変えると
鍵が変わり、`FixtureClient` は KeyError を投げる。これは不便ではなく、
「評価の条件が変わったことを黙って通さない」ための仕掛けである。

実行:  docker compose exec app python src/review03/cassette_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from layer_lab import MAX_CHARS, TOP_K, answerable, bm25_index, load_all  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.llm import FixtureClient, cache_key  # noqa: E402

# カセットを作ったときの条件（tools/make_fixtures.py の前提）。
# ここに書いていないものを変えても鍵は動かない。書いてあるものは全部が鍵に効く。
FROZEN: dict[str, object] = {
    "コーパス": "corpus/docs.jsonl（tools/make_corpus.py・固定シード）",
    "チャンク方式": "fixed(400/80)",
    "検索器": "LexicalIndex（BM25・形態素・k1=1.2・b=0.75）",
    "上位k件": TOP_K,
    "コンテキスト上限": MAX_CHARS,
    "システムプロンプト": "ragkit.answer.SYSTEM_PROMPT",
}

# 回帰が落ちたときに、上から順に確かめる。**先に犯人を決めない**
TRIAGE = (
    "カセットを作り直したか（tools/make_fixtures.py を実行したか）",
    "コーパスを作り直したか（tools/make_corpus.py の出力が変わっていないか）",
    "チャンク方式・BM25 のパラメータを変えていないか",
    "上位k件・コンテキスト上限を変えていないか",
    "ragkit.answer.SYSTEM_PROMPT を編集していないか",
    "検索の並び順が変わっていないか（リランク・融合・同義語展開を足していないか）",
    "以上がすべて同じなら、変わったのは後処理か指標の実装である",
)


def key_of(query_text: str, hits, max_chars: int = MAX_CHARS,
           system: str = SYSTEM_PROMPT) -> str:
    """その検索結果で生成を呼んだときの、カセットの鍵。"""
    return cache_key(system, build_user_prompt(query_text, hits, max_chars=max_chars))


def probe(query_text: str, hits) -> dict[str, str]:
    """条件を1つずつ変えて、鍵がどう動くかを並べる。"""
    return {
        "基準（k=5・2000字・凍結プロンプト）": key_of(query_text, hits),
        "順位だけ入れ替える（リランク相当）": key_of(query_text, list(reversed(hits))),
        "コンテキスト上限を1000字にする": key_of(query_text, hits, max_chars=1000),
        "システムプロンプトに空白を1つ足す": key_of(query_text, hits,
                                                    system=SYSTEM_PROMPT + " "),
        "候補を1件減らす": key_of(query_text, hits[:-1]),
    }


def replay(client, query_text: str, hits, max_chars: int = MAX_CHARS):
    """カセットから応答を取り出す。登録外なら KeyError がそのまま上がる。"""
    return client.complete(SYSTEM_PROMPT, build_user_prompt(query_text, hits,
                                                            max_chars=max_chars))


def main() -> None:
    _, queries, qrels, chunks = load_all()
    index = bm25_index(chunks)
    q = answerable(queries, qrels)[0]
    hits = index.search(q.text, k=TOP_K)

    print("[凍結している条件]")
    for key, value in FROZEN.items():
        print(f"  {key:<20}: {value}")

    print(f"\n[鍵の動き] クエリ {q.query_id}「{q.text}」")
    base = None
    for label, key in probe(q.text, hits).items():
        mark = "基準" if base is None else ("同じ" if key == base else "変わった")
        base = key if base is None else base
        print(f"  {label:<34} {key}  {mark}")

    client = FixtureClient("answers_v1")
    print("\n[再生]")
    print(f"  基準の入力            : {replay(client, q.text, hits).source} で再生できた")
    try:
        replay(client, q.text, list(reversed(hits)))
        print("  順位を入れ替えた入力  : 再生できてしまった（想定外）")
    except KeyError:
        print("  順位を入れ替えた入力  : KeyError（カセットに無い）")

    print("\n[回帰が落ちたときの切り分け]")
    for i, line in enumerate(TRIAGE, start=1):
        print(f"  {i}. {line}")


if __name__ == "__main__":
    main()
