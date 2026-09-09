#!/usr/bin/env python3
"""セッション5: 検索の共通入口（Retriever）。

検索を「基盤モデルから呼べる1つの口」にまとめます。オーケストレータ・エージェント・
MCP サーバー・バッチのどれから呼ばれても、入口はこの `search()` 1本です。
検索方式（セマンティック／ハイブリッド／ハイブリッド＋リランク）は引数で切り替えます。

    search(agent, "有給休暇 繰越 上限", mode="HYBRID_RERANK")

`TOOL_SPEC` は Converse API の `toolConfig` に載せる定義です。エージェントから実際に
呼び出す実装はセッション7・8で扱います。本章は「入口の形をどう決めるか」までです。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")

KB_ID = "SAMPLEKB01"

MODES = ("SEMANTIC", "HYBRID", "HYBRID_RERANK")

# 実 AWS では Bedrock のリランクモデル（Amazon Rerank / Cohere Rerank）の ARN を渡します。
# 同梱モックのカタログ（7モデル）にリランクモデルは含まれないため、この ARN は
# InvokeModel や Converse では使えません。Rerank API のモックは ARN を検証せず、
# 「クエリの語がどれだけ本文に現れるか」で並べ替えます。
RERANK_MODEL_ARN = "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0"

# クエリ書き換えで拾う社内用語。実務では基盤モデルか Amazon Kendra に任せる工程ですが、
# ここでは結果を再現できるように、決定的な用語辞書で抽出します。
KEYWORD_TERMS = [
    "有給休暇",
    "繰越",
    "上限",
    "在宅勤務",
    "資格取得",
    "出張旅費",
    "宿泊費",
    "備品",
    "交際費",
    "パスワード",
    "VPN",
    "生成AI",
    "機密",
    "インシデント",
]


def to_keywords(question: str, *, terms: list[str] | None = None) -> str:
    """自然文の質問を、キーワード検索が効く形（半角スペース区切り）に書き換える。

    ハイブリッド検索のキーワード側は「語」で効きます。「有給休暇の繰越上限は何日ですか？」を
    そのまま渡すと、助詞ごと1語として扱われてどの文書にも一致せず、
    **ハイブリッドにした意味が消えます**。書き換えは検索方式の選択と同じくらい効きます。
    """
    vocabulary = KEYWORD_TERMS if terms is None else terms
    return " ".join(term for term in vocabulary if term in question)


def _as_hit(result: dict) -> dict:
    """`Retrieve` のレスポンスを、章をまたいで使える形に正規化する。"""
    metadata = result.get("metadata") or {}
    return {
        "uri": (result.get("location") or {}).get("s3Location", {}).get("uri", ""),
        "title": metadata.get("title", ""),
        "category": metadata.get("category", ""),
        "updated_at": metadata.get("updatedAt", ""),
        "text": (result.get("content") or {}).get("text", ""),
        "score": float(result.get("score", 0.0)),
    }


def retrieve(
    agent,
    query: str,
    *,
    search_type: str = "HYBRID",
    top_k: int = 3,
    category: str | None = None,
) -> list[dict]:
    """Knowledge Bases の `Retrieve` を呼ぶ。

    `overrideSearchType` に `SEMANTIC` / `HYBRID` を渡して検索方式を切り替えます。
    既定は Knowledge Bases 側の設定（ベクトルストアが対応していれば `HYBRID`）に従うため、
    **方式を意図して固定したいときは必ず明示**します。
    """
    config: dict = {"numberOfResults": top_k, "overrideSearchType": search_type}
    if category is not None:
        config["filter"] = {"equals": {"key": "category", "value": category}}
    response = agent.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": config},
    )
    return [_as_hit(r) for r in response["retrievalResults"]]


def rerank(agent, query: str, hits: list[dict], *, top_n: int = 3) -> list[dict]:
    """`Rerank` API で候補を並べ直す。

    リランカはクエリと候補を**組で**評価します（検索は両者を別々にベクトル化して
    距離を測るだけ）。だから「検索で広く取り、リランクで絞る」の二段が効きます。
    レスポンスの `index` は**渡した順番の添字**なので、必ず元の候補に対応づけて戻します。
    """
    if not hits:
        return []
    response = agent.rerank(
        queries=[{"type": "TEXT", "textQuery": {"text": query}}],
        sources=[
            {
                "type": "INLINE",
                "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {"text": hit["text"]},
                },
            }
            for hit in hits
        ],
        rerankingConfiguration={
            "type": "BEDROCK_RERANKING_MODEL",
            "bedrockRerankingConfiguration": {
                "numberOfResults": top_n,
                "modelConfiguration": {"modelArn": RERANK_MODEL_ARN},
            },
        },
    )
    reordered: list[dict] = []
    for entry in response["results"]:
        hit = dict(hits[entry["index"]])
        hit["rerank_score"] = float(entry["relevanceScore"])
        hit["source_index"] = int(entry["index"])
        reordered.append(hit)
    return reordered


def search(
    agent,
    query: str,
    *,
    mode: str = "HYBRID",
    top_k: int = 3,
    candidate_k: int = 10,
    category: str | None = None,
) -> list[dict]:
    """検索の唯一の入口。呼び出し側は方式の実装を知らなくてよい。

    `HYBRID_RERANK` だけが2段構えです（`candidate_k` 件を広く取り、リランクで `top_k` に絞る）。
    入口を1つにしておくと、方式の変更・重みの調整・リランクの有無を
    呼び出し側のコードに触らずに切り替えられます。
    """
    if mode not in MODES:
        raise ValueError(f"mode は {MODES} のいずれかです: {mode}")
    if mode == "HYBRID_RERANK":
        candidates = retrieve(
            agent, query, search_type="HYBRID", top_k=candidate_k, category=category
        )
        return rerank(agent, query, candidates, top_n=top_k)
    return retrieve(agent, query, search_type=mode, top_k=top_k, category=category)


# Converse API の toolConfig に載せる定義。基盤モデルはこの説明文だけを手がかりに
# 「いつ検索を呼ぶか」「何を渡すか」を決めるため、description は仕様書として書く
TOOL_SPEC = {
    "toolSpec": {
        "name": "search_internal_docs",
        "description": (
            "サンプル商事の社内規程・ヘルプデスク文書を検索し、出典付きの抜粋を上位k件返す。"
            "社内の制度・手続き・上限額・申請期限に関する質問では必ず呼び出すこと。"
            "query は助詞を落とし、語を半角スペースで区切った検索語にすること。"
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索語。例: 有給休暇 繰越 上限",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["IT", "経費", "人事", "セキュリティ"],
                        "description": "分類で絞る場合のみ指定する。誤ると正解が母集団から消える",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返す件数。既定は3。多く返すほど文脈は増えるがコストも増える",
                    },
                },
                "required": ["query"],
            }
        },
    }
}
