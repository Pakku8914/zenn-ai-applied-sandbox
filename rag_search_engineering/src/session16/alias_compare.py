#!/usr/bin/env python3
"""エイリアス切り替えを OpenSearch でもやってみる（任意）。

OpenSearch は既定では起動していない。先に次を実行すること。

    docker compose --profile search-engine up -d
    python src/session16/alias_compare.py

起動していなければ、何もせずに終わる（この章の他の検証は Qdrant だけで完結する）。
クラスタ運用・シャード設計は本書の範囲外。ここで見るのは「別の製品でも、
版の切り替えは同じ形（並行構築 → 原子的な付け替え → 切り戻し）になる」ことだけ。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

OS_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
ALIAS = "minato_s16"
V1, V2 = "minato_s16_v1", "minato_s16_v2"


def request(method: str, path: str, body=None, timeout: int = 30):
    url = OS_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def is_available(timeout: int = 3) -> bool:
    try:
        request("GET", "/", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def delete_index(name: str) -> None:
    try:
        request("DELETE", f"/{name}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def build(name: str, method: str) -> None:
    delete_index(name)
    request("PUT", f"/{name}", {
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {"properties": {"method": {"type": "keyword"},
                                    "text": {"type": "text", "analyzer": "cjk"}}},
    })
    for i in range(3):
        request("PUT", f"/{name}/_doc/{i}",
                {"method": method, "text": f"みなと商事の申請手順 {i}"})
    request("POST", f"/{name}/_refresh")


def alias_target() -> str | None:
    try:
        res = request("GET", f"/_alias/{ALIAS}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return next(iter(res), None)


def switch_alias(target: str) -> None:
    """付け替えを1リクエストにまとめる（remove と add が同時に反映される）。"""
    actions = []
    current = alias_target()
    if current:
        actions.append({"remove": {"index": current, "alias": ALIAS}})
    actions.append({"add": {"index": target, "alias": ALIAS}})
    request("POST", "/_aliases", {"actions": actions})


def method_via_alias() -> str:
    res = request("POST", f"/{ALIAS}/_search", {"query": {"match_all": {}}, "size": 1})
    return res["hits"]["hits"][0]["_source"]["method"]


def run_switch() -> list[tuple[str, bool]]:
    """並行構築 → 切り替え → 切り戻しを実行して、検査結果を返す。"""
    build(V1, "fixed")
    switch_alias(V1)
    before = method_via_alias()
    build(V2, "heading")  # 並行構築（検索は V1 のまま）
    during = method_via_alias()
    switch_alias(V2)
    after = method_via_alias()
    switch_alias(V1)
    back = method_via_alias()
    delete_index(V1)
    delete_index(V2)
    return [
        ("切り替え前はエイリアスが v1 を指す", before == "fixed"),
        ("並行構築中も検索先は v1 のまま", during == "fixed"),
        ("付け替えると検索先が v2 になる", after == "heading"),
        ("切り戻せる", back == "fixed"),
    ]


def main() -> None:
    if not is_available():
        print(f"OpenSearch ({OS_URL}) に接続できません。")
        print("  docker compose --profile search-engine up -d")
        print("を実行してから、もう一度試してください（この章の他の検証には不要です）。")
        return

    info = request("GET", "/")
    print(f"OpenSearch {info['version']['number']} に接続しました\n")
    for label, ok in run_switch():
        print(f"  {'OK ' if ok else 'NG '} {label}")

    print("\n  Qdrant                          OpenSearch")
    print("  update_collection_aliases       POST /_aliases")
    print("  delete + create を1リクエスト    remove + add を1リクエスト")
    print("  コレクション名を隠す             インデックス名を隠す")
    print("\nどちらも「別名を1つ用意して、実体を裏で入れ替える」という同じ形。")
    print("覚えるのは製品ごとの API ではなく、手順の形のほう。")


if __name__ == "__main__":
    main()
