#!/usr/bin/env python3
"""参照関係のグラフを作り、規模と質を数える。

  docker compose exec app python src/session14/build_graph.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import (  # noqa: E402
    Bench,
    DocGraph,
    build_name_index,
    candidate_expressions,
    dangling_references,
)


def main() -> None:
    bench = Bench()
    g = bench.graph
    docs = bench.docs

    print("=== セッション14：参照関係のグラフを作る ===")
    print(f"文書 {len(docs)} / 部署 {len(g.depts)} / ノード {g.n_nodes}")
    print(f"所管エッジ（メタデータから0円で作れる）: {len(docs)}")

    index = build_name_index(docs)
    covered = sum(len(v) for v in index.values())
    ambiguous_names = [n for n, ids in index.items() if len(ids) > 1]
    print("\n参照名の辞書")
    print(f"  項目数             : {len(index)}")
    print(f"  ひも付く文書       : {covered}")
    print(f"  複数文書を指す項目 : {len(ambiguous_names)}")

    ambiguous = [m for m in g.mentions if m.ambiguous]
    print("\n本文から拾った言及")
    print(f"  言及の総数     : {len(g.mentions)}")
    print(f"  参照先が一意   : {len(g.mentions) - len(ambiguous)}")
    print(f"  参照先が複数   : {len(ambiguous)}")
    print(f"  自己参照       : {sum(1 for m in g.mentions if m.src in m.candidates)}")

    print("\nエッジ（参照先が絞れないときは候補すべてにつなぐ: link=all）")
    print(f"  合計           : {len(g.edges)}")
    for kind in ("related", "mentions", "delegates_to"):
        print(f"  {kind:<14}: {len(g.edges_of(kind))}")
    print(f"  参照を持つ文書 : {len(g.adj_out)}")
    print(f"  参照される文書 : {len(g.adj_in)}")

    newest = DocGraph(docs, link="newest")
    print(f"  link=newest なら合計 {len(newest.edges)} 本（曖昧な参照を1本に絞るため）")

    cross = g.cross_theme_edges()
    ratio = len(cross) / len(g.edges) * 100
    print(f"\nテーマ（語彙のかたまり）をまたぐエッジ: {len(cross)} / {len(g.edges)} ({ratio:.1f}%)")
    for e in cross:
        print(f"  {g.label(e.src)}")
        print(f"      --{e.kind}--> {g.label(e.dst)}")

    structural = sum(len(candidate_expressions(d)) for d in docs)
    dangling = dangling_references(docs, index)
    print(f"\n書式から拾える参照表現: {structural}（うち解決できないもの {len(dangling)}）")

    print("\n曖昧な参照の例")
    sample = next(m for m in g.mentions if m.ambiguous and m.name.endswith("規程"))
    print(f"  {g.label(sample.src)}")
    print(f"    本文の「{sample.name}」が指しうる文書:")
    for doc_id in sample.candidates:
        print(f"      {g.label(doc_id)}（{g.docs[doc_id].updated_at}）")
    picked = newest.resolve(sample)[0]
    print(f"    link=newest が選ぶのは {g.label(picked)} だけ（旧版を引かない）")


if __name__ == "__main__":
    main()
