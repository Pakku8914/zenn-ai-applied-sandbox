#!/usr/bin/env python3
"""グラフの構築コストと維持コストを、呼び出し回数の算術で見積もる。

  docker compose exec app python src/session14/cost_model.py

LLM は StubClient（決定的なスタブ）だけを使う。APIキーは不要で、課金も発生しない。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_lab import (  # noqa: E402
    Bench,
    DocGraph,
    build_name_index,
    dangling_references,
)

from ragkit.llm import StubClient  # noqa: E402
from ragkit.models import Doc  # noqa: E402

EXTRACT_SYSTEM = (
    "あなたは社内文書の参照関係を抽出する担当です。"
    "本文が参照している別の文書の名前だけを JSON で返してください。"
)

# 章の演習用の決定的なスタブ。実 API の応答ではない（FixtureClient も使わない）
STUB_RULES = {
    "情報の持ち出しに関する補則": '{"references": ["USBメモリの利用規程"]}',
    "外部サービスの利用申請に関する補則": '{"references": ["セキュリティ事故の報告規程"]}',
    "PCの返却に関する補則": '{"references": ["退職時のアカウント停止規程"]}',
}


def extract_prompt(doc: Doc) -> str:
    return (
        f"# 文書\nタイトル: {doc.title}\n\n本文:\n{doc.body}\n\n"
        '# 出力\n{"references": ["文書名", ...]} の形式だけを返してください。'
    )


def make_stub() -> StubClient:
    return StubClient(STUB_RULES, default='{"references": []}')


def llm_extract(client, doc: Doc, index: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """LLM の応答を辞書で解決して doc_id にする。抽出と解決は別の工程。"""
    res = client.complete(EXTRACT_SYSTEM, extract_prompt(doc))
    names = json.loads(res.text).get("references", [])
    out: list[str] = []
    for name in names:
        out.extend(index.get(name, ()))
    return tuple(sorted(set(out)))


def calls(n_docs: int, calls_per_doc: int = 1, passes: int = 1) -> int:
    """LLM 抽出に必要な呼び出し回数。単価は契約によるので回数だけを見積もる。"""
    return n_docs * calls_per_doc * passes


def main() -> None:
    bench = Bench()
    docs = bench.docs
    g = bench.graph
    index = build_name_index(docs)

    print("=== 構築コスト（一度きり）===")
    print(f"  文書数                   : {len(docs)}")
    print(f"  辞書の項目数             : {len(index)}")
    print(f"  ルールベースの照合回数   : {len(index) * len(docs):,}（LLM 呼び出し 0 回）")
    print(f"  LLM 抽出（1文書1回）     : {calls(len(docs)):,} 回")
    print(f"  LLM 抽出（本文2分割×2工程）: {calls(len(docs), 2, 2):,} 回")

    print("\n=== 得られるもの ===")
    cross = g.cross_theme_edges()
    print(f"  エッジ                   : {len(g.edges)} 本")
    print(f"  テーマをまたぐエッジ     : {len(cross)} 本")
    per_edge = calls(len(docs)) / len(cross)
    print(f"  LLM 抽出のとき、テーマをまたぐエッジ 1 本あたり {per_edge:.1f} 回の呼び出し")

    print("\n=== 維持コスト（改訂のたびに払う）===")
    by_date = Counter(d.updated_at for d in docs)
    for date, n in sorted(by_date.items()):
        print(f"  {date}: {n} 文書")
    latest = max(by_date)
    print(f"  直近の改訂（{latest}）で動いた文書 : {by_date[latest]}")
    print(f"  再抽出（1文書1回）               : {calls(by_date[latest]):,} 回")
    print("  参照名の解決は全体でやり直す（他の文書からの参照が壊れうるため）")

    print("\n=== 見積もり表 ===")
    print("| 方式 | 事前のLLM呼び出し | 直近の改訂ぶん | 質問1件あたり |")
    print("| :--- | ---: | ---: | :--- |")
    print("| ルールベース辞書 | 0 | 0 | 0 |")
    print(f"| LLM 抽出（1文書1回） | {calls(len(docs))} | {calls(by_date[latest])} | 0 |")
    print(f"| LLM 抽出（2分割×2工程） | {calls(len(docs), 2, 2)} | "
          f"{calls(by_date[latest], 2, 2)} | 0 |")
    print("| 参照追跡（多段検索） | 0 | 0 | 委任表現の数だけ追加検索 |")

    print("\n=== LLM 抽出はルールベースより良い答えを出すか（StubClient で確認）===")
    stub = make_stub()
    for e in cross:
        doc = bench.by_id[e.src]
        got = llm_extract(stub, doc, index)
        rule = tuple(sorted(g.neighbors(e.src, kinds=("delegates_to",))))
        mark = "一致" if got == rule else "不一致"
        print(f"  {doc.doc_id} {doc.title}")
        print(f"    LLM   : {got}")
        print(f"    ルール: {rule} … {mark}")
    print("  この3件では同じ答えです。差が出るのは、書き方が揺れている文書だけです。")
    print("  実 API での確認は任意課題（課金あり）。本章の結論には必要ありません。")

    print("\n=== 維持できないグラフ（タイトルを1つ変えてみる）===")
    target = bench.doc_id("USBメモリの利用規程")
    renamed = [replace(d, title="USBメモリ等の外部記録媒体の利用規程") if d.doc_id == target else d
               for d in docs]
    g2 = DocGraph(renamed)
    index2 = build_name_index(renamed)
    print(f"  変更前: エッジ {len(g.edges)} / {target} への参照 {g.in_degree(target)} 本")
    print(f"  変更後: エッジ {len(g2.edges)} / {target} への参照 {g2.in_degree(target)} 本")
    print(f"  辞書だけを見ていると、消えた {len(g.edges) - len(g2.edges)} 本には気づけません。")
    dangling = dangling_references(renamed, index2)
    print(f"  書式から拾う検査を併用すると、リンク切れ {len(dangling)} 件として検出できます:")
    for doc_id, name in dangling:
        print(f"    {doc_id} 本文の「{name}」が解決できない")


if __name__ == "__main__":
    main()
