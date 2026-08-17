#!/usr/bin/env python3
"""中間プロジェクト02：上限測定のカセットを用意し、「条件を変えたら1本増える」を目で見る。

    docker compose exec app python src/mid02/make_cassette.py

上限測定では検索結果ではなく「判定データから作った正解チャンク」を渡す。
コンテキストが変わればプロンプトが変わり、プロンプトが変われば鍵が変わる。
つまり `fixtures/answers_v1.json` は1件も当たらない。**カセットは条件ごとに1本ずつ増える。**

カセットの生成器はセッション12で書いたものをそのまま使う（同じものを2つ持たない）。
プロジェクトで新しく作るのは製品側のコードと判断の記録であって、測定の道具ではない。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # sandbox/
for _p in (str(ROOT), str(ROOT / "src" / "session12"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pipeline as pl  # noqa: E402
from eval_lab import MAX_CHARS, TOP_K, Bench  # noqa: E402
from make_gold_cassette import CASSETTE, build  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.llm import FixtureClient  # noqa: E402

# 鍵に効く条件。ここに書いていないものを変えても鍵は動かない
FROZEN: dict[str, object] = {
    "コーパス": "corpus/docs.jsonl（tools/make_corpus.py・固定シード）",
    "チャンク方式": f"{pl.CHUNK_METHOD}({pl.CHUNK_SIZE}/{pl.CHUNK_OVERLAP})",
    "検索器": "LexicalIndex（BM25・形態素）",
    "上位k件": pl.TOP_K,
    "コンテキスト上限": pl.MAX_CHARS,
    "システムプロンプト": "ragkit.answer.SYSTEM_PROMPT",
}


def matches_session12() -> bool:
    """製品側の凍結条件が、セッション12の測定条件と一致しているか。

    ここがずれていると、測った数字と動いている製品が別物になる。
    """
    return (pl.TOP_K, pl.MAX_CHARS) == (TOP_K, MAX_CHARS)


def ensure_gold_cassette(bench: Bench | None = None) -> FixtureClient:
    """上限測定用のカセットを開く。無ければその場で作る。"""
    try:
        return FixtureClient(CASSETTE)
    except FileNotFoundError:
        build(bench or Bench())
        return FixtureClient(CASSETTE)


def miss_count(bench: Bench, client: FixtureClient, n: int = 30) -> int:
    """上限測定のプロンプトを既存カセットに投げて、何件が KeyError になるかを数える。"""
    misses = 0
    for q in bench.queries[:n]:
        user = build_user_prompt(q.text, bench.gold_hits(q), max_chars=pl.MAX_CHARS)
        try:
            client.complete(SYSTEM_PROMPT, user)
        except KeyError:
            misses += 1
    return misses


def main() -> None:
    bench = Bench()

    print("[凍結している条件]")
    for key, value in FROZEN.items():
        print(f"  {key:<20}: {value}")
    print(f"  セッション12の測定条件と一致: {matches_session12()}")

    ensure_gold_cassette(bench)
    print(f"\n[上限測定用カセット] fixtures/{CASSETTE}.json を用意しました")

    misses = miss_count(bench, FixtureClient("answers_v1"))
    print(f"[鍵の突き合わせ] 上限測定のプロンプトを answers_v1 に投げると {misses}/30 件が KeyError")
    print("コンテキストを変えた時点でカセットが1本増える。これが再現性の値段である。")


if __name__ == "__main__":
    main()
