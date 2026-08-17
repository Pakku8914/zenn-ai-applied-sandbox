#!/usr/bin/env python3
"""同じ索引を全文検索エンジンにも作らせて、自作 BM25 と突き合わせる。

OpenSearch は既定では起動していない。先に次を実行すること。

    docker compose --profile search-engine up -d

公式クライアントは入れず、標準ライブラリ（urllib）で REST を直接叩く。
依存を増やさずに済むうえ、やりとりしている JSON がそのまま見えるため。

    python src/session05/opensearch_compare.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import hits_to_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

OS_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
INDEX = "minato_docs_fixed"

# k1・b を明示する。既定値に依存すると「自作と同じ設定か」が確認できない
INDEX_BODY = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "similarity": {"bm25_tuned": {"type": "BM25", "k1": 1.2, "b": 0.75}},
        }
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            # cjk アナライザは文字 bi-gram を作る（Lucene 組み込み・プラグイン不要）
            "text": {"type": "text", "analyzer": "cjk", "similarity": "bm25_tuned"},
        }
    },
}


def request(method: str, path: str, body=None, ndjson: bool = False, timeout: int = 60):
    url = OS_URL.rstrip("/") + path
    data, headers = None, {}
    if ndjson:
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/x-ndjson"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def is_available(timeout: int = 3) -> bool:
    try:
        request("GET", "/", timeout=timeout)
        return True
    except Exception:
        return False


def analyze(text: str, analyzer: str) -> list[str]:
    res = request("POST", "/_analyze", {"analyzer": analyzer, "text": text})
    return [t["token"] for t in res["tokens"]]


def rebuild(chunks) -> None:
    try:
        request("DELETE", f"/{INDEX}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    request("PUT", f"/{INDEX}", INDEX_BODY)
    lines = []
    for c in chunks:
        lines.append(json.dumps({"index": {"_index": INDEX, "_id": c.chunk_id}}))
        lines.append(json.dumps(
            {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "text": c.text}, ensure_ascii=False))
    res = request("POST", "/_bulk", "\n".join(lines) + "\n", ndjson=True)
    if res.get("errors"):
        raise RuntimeError("bulk indexing に失敗しました")
    request("POST", f"/{INDEX}/_refresh")


def search(query: str, k: int = 10) -> list[tuple[str, str, float]]:
    res = request("POST", f"/{INDEX}/_search",
                  {"query": {"match": {"text": query}}, "size": k})
    return [(h["_source"]["chunk_id"], h["_source"]["doc_id"], h["_score"])
            for h in res["hits"]["hits"]]


def main() -> None:
    if not is_available():
        print(f"OpenSearch ({OS_URL}) に接続できません。")
        print("  docker compose --profile search-engine up -d")
        print("を実行してから、もう一度試してください。")
        return

    info = request("GET", "/")
    print(f"OpenSearch {info['version']['number']} に接続しました")

    print("\n=== アナライザの違い（同じ文字列がどう割れるか）===")
    for text in ("多要素認証", "MFA", "MN-Book15"):
        for analyzer in ("cjk", "standard"):
            print(f"{analyzer:<9}{text} -> {analyze(text, analyzer)}")

    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    print(f"\n{len(chunks)} チャンクを登録します...")
    rebuild(chunks)
    count = request("GET", "/" + INDEX + "/_count")["count"]
    print(f"登録件数: {count}")

    mine = LexicalIndex(mode="bigram").build(chunks)
    print("\n=== 上位10件の一致（自作 bigram BM25 と OpenSearch cjk）===")
    for q in [q for q in queries if q.type in ("keyword", "abbrev")][:5]:
        os_docs = []
        for _, doc_id, _ in search(q.text, k=10):
            if doc_id not in os_docs:
                os_docs.append(doc_id)
        my_docs = hits_to_docs(mine.search(q.text, k=10))
        overlap = len(set(os_docs) & set(my_docs))
        rel = {d for d, g in qrels.get(q.query_id, {}).items() if g >= 1}
        print(f"{q.query_id} ({q.type}) 共通={overlap}/10  "
              f"適合 自作={len(set(my_docs) & rel)} OpenSearch={len(set(os_docs) & rel)}  "
              f"{q.text}")

    print("\nスコアの絶対値は一致しません（Lucene は (k1+1) を掛けず、")
    print("文書長を1バイトに量子化して保持するため）。比べるのは順位です。")


if __name__ == "__main__":
    main()
