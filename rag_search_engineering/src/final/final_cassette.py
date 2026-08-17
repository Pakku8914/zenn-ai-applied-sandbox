#!/usr/bin/env python3
"""最終プロジェクト：構成を変えたので、合成カセットを作り直す。

    docker compose exec app python src/final/final_cassette.py

カセットの鍵は**プロンプト全体の SHA-256** である。最終プロジェクトでは

  - クエリ側の同義語展開を足した（1段目の結果が変わる）
  - 権限フィルタを足した（利用者によってコンテキストが変わる）

ので、セッション12・mid02 のカセット（`answers_v1`）は当たらなくなる。
**これは不便ではなく、条件が変わったことを黙って通さないための仕掛けである。**

生成物: `fixtures/answers_final_v1.json`
  構成2つ（baseline-v0 / final-v1）× 役割2つ（member / manager）× クエリ120件
  ぶんの鍵が1本のファイルに入る。同じプロンプトになった組み合わせは鍵が共有される
  ので、実際の鍵の本数は 480 より少ない（**手元の出力を記録してください**）。

ファイル名を `make_cassette.py` にしていないのは、`src/mid02/make_cassette.py` と
名前が衝突するため（最終プロジェクトは mid02 の実装も読み込む）。

APIキーは不要（実 API の記録ではなく、固定シードの合成データを組み立てている）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from reuse import post, synth  # noqa: E402
from search_platform import ADOPTED, BASELINE, ROLES, SearchPlatform  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.corpus import load_qrels, load_queries  # noqa: E402
from ragkit.llm import FIXTURE_DIR, FixtureClient, StubClient, cache_key  # noqa: E402

CASSETTE = ADOPTED.cassette
PROFILES = (BASELINE, ADOPTED)


def build(name: str = CASSETTE) -> dict:
    """4通りの条件ぶんの鍵を1本のカセットに書き出し、集計を返す。

    チャンクと索引は全構成で共通（比較の土俵を動かさない）。
    """
    queries, qrels = load_queries(), load_qrels()

    data: dict[str, dict] = {}
    per_condition: dict[str, list[str]] = {}
    for config in PROFILES:
        # カセットを作る段階では生成しないので、クライアントはスタブでよい
        platform = SearchPlatform(config, client=StubClient())
        for role, principal in ROLES.items():
            keys: list[str] = []
            for q in queries:
                hits = platform.retrieve(principal, q.text)
                user = build_user_prompt(q.text, hits, max_chars=config.max_chars)
                key = cache_key(SYSTEM_PROMPT, user)
                keys.append(key)
                # 引用は「実際にコンテキストへ載ったチャンク」からしか出さない
                # （製品側が strict_citations=True なので、母集合をそろえておく）
                loaded = set(post.context_ids(hits, config.max_chars))
                in_context = [h for h in hits if h.chunk_id in loaded]
                payload = synth.synth_answer(q, in_context, qrels.get(q.query_id, {}))
                text = json.dumps(payload, ensure_ascii=False)
                data[key] = {
                    "text": text, "query_id": q.query_id, "profile": config.name,
                    "role": role, "n_context": len(in_context),
                    "input_tokens": len(user) // 3, "output_tokens": len(text) // 3,
                }
            per_condition[f"{config.name}/{role}"] = keys

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    base_keys = per_condition[f"{BASELINE.name}/member"]
    final_keys = per_condition[f"{ADOPTED.name}/member"]
    manager_keys = per_condition[f"{ADOPTED.name}/manager"]
    return {
        "path": str(path),
        "keys": len(data),
        "conditions": len(per_condition),
        "queries": len(queries),
        # 同義語展開で鍵が変わったクエリ数（＝カセットを作り直す理由）
        "changed_by_synonyms": sum(1 for a, b in zip(base_keys, final_keys) if a != b),
        # 権限で鍵が変わったクエリ数（＝カセットは権限の数だけ要る）
        "changed_by_role": sum(1 for a, b in zip(final_keys, manager_keys) if a != b),
    }


def ensure_cassette(name: str = CASSETTE) -> FixtureClient:
    """カセットを開く。無ければその場で作る（手順を忘れても止まらないように）。"""
    try:
        return FixtureClient(name)
    except FileNotFoundError:
        build(name)
        return FixtureClient(name)


def miss_count(platform: SearchPlatform | None = None, role: str = "member",
               cassette: str = "answers_v1", n: int = 120) -> tuple[int, int]:
    """新しい構成のプロンプトを**古いカセット**に投げ、何件が KeyError になるかを数える。

    先頭 30 件だけを試すと 0 件になることがある（略語クエリは Q-067 以降に固まっており、
    同義語展開はそこでしか発火しないため）。**どのクエリで試すかで見え方が変わる**ので、
    既定では 120 件すべてを投げる。
    """
    old = FixtureClient(cassette)
    platform = platform or SearchPlatform(ADOPTED, client=StubClient())
    principal = ROLES[role]
    misses = 0
    queries = load_queries()[:n]
    for q in queries:
        user, _key = platform.prompt_key(principal, q.text)
        try:
            old.complete(SYSTEM_PROMPT, user)
        except KeyError:
            misses += 1
    return misses, len(queries)


def main() -> None:
    stats = build()
    print(f"{stats['path']} を書きました")
    print(f"  条件の組み合わせ : {stats['conditions']} 通り × クエリ {stats['queries']} 件 "
          f"= {stats['conditions'] * stats['queries']} 回分")
    print(f"  実際の鍵の本数   : {stats['keys']} 本（同じプロンプトは鍵を共有する）")
    print(f"  同義語展開で鍵が変わったクエリ : {stats['changed_by_synonyms']} 件")
    print(f"  権限で鍵が変わったクエリ       : {stats['changed_by_role']} 件")

    misses, probed = miss_count()
    print(f"\n[鍵の突き合わせ] 新構成のプロンプトを answers_v1 に投げると "
          f"{misses}/{probed} 件が KeyError")
    print("条件を変えた時点でカセットが増える。これが再現性の値段である。")
    print("※ 件数は手元の実行結果を成果物①（検索設計書）に記録してください。")


if __name__ == "__main__":
    main()
