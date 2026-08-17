#!/usr/bin/env python3
"""中間プロジェクト01：社内FAQ検索の「条件」を1か所で定義する。

新しい検索方式はここには無い。セッション4〜8で作った部品を、比較できる
「条件」として名前付きで束ねるだけの薄い層に保つ。条件の定義が散らばると、
評価スクリプトの中身とチューニング記録の行が静かにずれていく。

  build_chunks / build_lexical / build_dense   索引の用意（密ベクトルは再利用）
  chunk_conditions / method_conditions / fusion_conditions   3段階の比較対象
  BASELINE / DENSE / ADOPTED                   順路の3点（成果物②の骨格）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.hybrid import HybridRetriever  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

# セッション6・7で作った密ベクトルのコレクション。作り直さず再利用する
COLLECTION = "minato_docs_fixed"

# チャンク方式のパラメータ（セッション4で比較した設定をそのまま使う）
CHUNK_PARAMS = {
    "fixed": dict(size=400, overlap=80),
    "sentence": dict(max_chars=400),
    "heading": dict(max_chars=600),
    "parent_window": dict(child=200, window=600),
}

# 統制変数：全段階でこのチャンク方式に固定する（理由は検索設計書 D1 に書く）
BASE_METHOD = "fixed"

# 順路の3点。ここの文字列がそのままレポートの行ラベルになるので、
# 記録と食い違わないよう定数にしておく
BASELINE = "bm25 / fixed"
DENSE = "dense / fixed"
ADOPTED = "hybrid minmax(候補50, 0.3:1.0)"


def build_chunks(method: str = BASE_METHOD):
    """コーパスを読み込んで指定方式でチャンクに割る。"""
    return chunk_all(load_docs(), method, **CHUNK_PARAMS[method])


def build_lexical(chunks) -> LexicalIndex:
    """BM25 索引。数秒で作れるので毎回作り直してよい。"""
    return LexicalIndex().build(chunks)


def build_dense(chunks, collection: str = COLLECTION):
    """密ベクトル索引。既にコレクションがあれば必ず再利用する。

    作り直すと 673 チャンクの符号化で約1分かかる。評価を何十回も回す
    プロジェクトでは、この1分が試行回数を確実に削る。
    """
    from ragkit.dense import DenseIndex

    index = DenseIndex(collection)
    if not index.client.collection_exists(collection):
        print(f"[mid01] {collection} が無いので作成します（1分程度・以降は再利用）")
        index.build(chunks)
    return index


def chunk_conditions() -> dict[str, LexicalIndex]:
    """段階1：チャンク方式だけを変える（検索方式は BM25 に固定）。"""
    return {f"bm25 / {m}": build_lexical(build_chunks(m)) for m in CHUNK_PARAMS}


def method_conditions(lex, dense) -> dict[str, object]:
    """段階2：検索方式だけを変える（チャンク方式は fixed に固定）。"""
    return {BASELINE: lex, DENSE: dense}


def fusion_conditions(lex, dense) -> dict[str, object]:
    """段階3：統合方式だけを変える（束ねる検索器は段階2と同一のもの）。

    重みは [bm25, dense] の順。0.3:1.0 は「弱い側の重みを下げる」設定。
    """
    return {
        "hybrid rrf(候補50, rrf_k=60)": HybridRetriever([lex, dense], 50, "rrf"),
        "hybrid rrf(候補10, rrf_k=60)": HybridRetriever([lex, dense], 10, "rrf"),
        "hybrid minmax(候補50, 1.0:1.0)": HybridRetriever([lex, dense], 50, "minmax", [1.0, 1.0]),
        ADOPTED: HybridRetriever([lex, dense], 50, "minmax", [0.3, 1.0]),
        # 重みの「向き」を確かめるための対照条件。強い側を下げると悪化することを見る
        "hybrid minmax(候補50, 1.0:0.3)": HybridRetriever([lex, dense], 50, "minmax", [1.0, 0.3]),
    }


def route_conditions(lex, dense) -> dict[str, object]:
    """採用に至る順路（基準線 → 検索方式 → 統合方式）の3点だけを返す。"""
    return {BASELINE: lex, DENSE: dense, ADOPTED: fusion_conditions(lex, dense)[ADOPTED]}
