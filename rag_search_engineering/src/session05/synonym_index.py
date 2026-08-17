#!/usr/bin/env python3
"""索引側の同義語展開。略語クエリを救うための最小の仕掛け。

正式名称を含むチャンクに、その別称を「索引に入れる語としてだけ」足す。
表示や生成に渡すテキストは元のまま変えない（読者に見せる本文を汚さない）。

クエリ側の書き換え（クエリ拡張・言い換え）はセッション10の主題なので、
ここでは索引側だけを扱う。

    python src/session05/synonym_index.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk  # noqa: E402

# 正式名称（コーパスに実在する語） -> 別称（クエリにだけ現れる語）
# 「みなと商事」のヘルプデスクで実際に使われている言い換えを人手で登録したもの
SYNONYMS: dict[str, list[str]] = {
    "有給休暇": ["年休", "有休"],
    "時間外労働": ["残業"],
    "育児休業": ["育休"],
    "通勤交通費": ["定期代"],
    "貸与PC": ["パソコン"],
    "貸与スマートフォン": ["スマホ", "携帯"],
    "パスワード": ["パス", "PW"],
    "多要素認証": ["MFA", "二要素認証", "2段階認証"],
    "入退館カード": ["社員証"],
    "座席": ["フリーアドレス"],
    "標的型メール": ["フィッシング", "不審メール"],
    "外部サービス": ["SaaS", "クラウドサービス"],
    "セキュリティ事故": ["インシデント"],
}
TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


class SynonymLexicalIndex(LexicalIndex):
    """索引を作るときだけ別称を足す BM25。検索の使い方は LexicalIndex と同じ。"""

    def __init__(self, synonyms: dict[str, list[str]], k1: float = 1.2,
                 b: float = 0.75, mode: str = "morph") -> None:
        super().__init__(k1=k1, b=b, mode=mode)
        self.synonyms = synonyms
        self.expanded_chunks = 0

    def expand(self, text: str) -> str:
        extra = [alias for term, aliases in self.synonyms.items()
                 if term in text for alias in aliases]
        return text + "\n" + " ".join(extra) if extra else text

    def build(self, chunks: list[Chunk]) -> "SynonymLexicalIndex":
        self.expanded_chunks = 0
        expanded: list[Chunk] = []
        for c in chunks:
            text = self.expand(c.text)
            if text != c.text:
                self.expanded_chunks += 1
            expanded.append(replace(c, text=text))
        super().build(expanded)
        # 索引は展開後の語で作り、返す本文は元のチャンクに戻す
        for c in chunks:
            self.chunks[c.chunk_id] = c
        return self


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)

    base = LexicalIndex().build(chunks)
    syn = SynonymLexicalIndex(SYNONYMS).build(chunks)

    rep_base = evaluate(base, queries, qrels, k=10, label="bm25 / fixed")
    rep_syn = evaluate(syn, queries, qrels, k=10, label="bm25 + 同義語 / fixed")
    rep_base.to_json(REPORT_DIR / "s05_synonym_before.json")
    rep_syn.to_json(REPORT_DIR / "s05_synonym_after.json")

    print("=== 索引側の同義語展開 ===")
    print(f"辞書のエントリ数={len(SYNONYMS)}  "
          f"展開されたチャンク={syn.expanded_chunks} / {len(chunks)}")
    print(f"語彙数 {len(base.postings)} -> {len(syn.postings)}")

    print(f"\n{'指標':<12}{'before':>10}{'after':>10}{'差':>10}")
    for key, name in (("recall", "Recall@10"), ("ndcg", "nDCG@10"),
                      ("mrr", "MRR"), ("precision", "P@10")):
        b, a = rep_base.macro[key], rep_syn.macro[key]
        print(f"{name:<12}{b:>10.3f}{a:>10.3f}{a - b:>+10.3f}")

    print(f"\n{'クエリ型':<18}{'before':>10}{'after':>10}{'差':>10}")
    for t in TYPES:
        b = rep_base.by_type[t]["recall"]
        a = rep_syn.by_type[t]["recall"]
        print(f"{t:<18}{b:>10.3f}{a:>10.3f}{a - b:>+10.3f}")


if __name__ == "__main__":
    main()
