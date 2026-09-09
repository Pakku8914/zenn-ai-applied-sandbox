#!/usr/bin/env python3
"""セッション5: 分け方（チャンキング）の実装。

Amazon Bedrock Knowledge Bases では、チャンキング戦略は「設定」で選びます
（Fixed size / Hierarchical / Semantic / No chunking / Lambda によるカスタム）。
その設定を作る API（`CreateDataSource`）は同梱モックにありません。そこで本章では
同じ考え方を Python の関数として実装し、対応表で試験の設定名に結び付けます。

    fixed_size        … Fixed-size chunking（maxTokens / overlapPercentage 相当）
    sentence_windows  … Semantic chunking の考え方（文の境界を壊さない）
    with_title_prefix … Hierarchical chunking の「親の見出しを子に持たせる」部分
    fetch_parent      … Hierarchical chunking の「子で当てて親を返す」部分（small-to-big）

単位の違いに注意してください。Knowledge Bases の設定はトークン数、この実装は文字数です。
本教材のトークン規則は「ASCII 4文字＝1トークン／非ASCII 1文字＝1トークン」なので、
日本語の文書では文字数とトークン数がほぼ一致します。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CORPUS_PATH = Path("/workspace/fixtures/kb_corpus.json")

SENTENCE_END = "。"
_SENTENCE_SPLIT = re.compile(r"(?<=。)")


def load_documents(path: Path = CORPUS_PATH) -> list[dict]:
    """社内文書12件を「分ける前の状態」で読む（`id` / `uri` / `title` / `text` ほか）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def split_sentences(text: str) -> list[str]:
    """句点の直後で切る。句点は前の文に残す（文末が消えると読み手が文の切れ目を失う）。"""
    return [s for s in _SENTENCE_SPLIT.split(text) if s]


def fixed_size(text: str, *, size: int, overlap: int = 0) -> list[str]:
    """固定長で切る。`overlap` 文字だけ直前のチャンクと重ねる。

    Knowledge Bases の Fixed-size chunking に対応します（`maxTokens` が `size`、
    `overlapPercentage` が `overlap / size`）。**文の途中で切れることを許す**代わりに、
    どんな文書でも同じ手順で処理でき、チャンク数を見積もれるのが利点です。
    """
    if size <= 0:
        raise ValueError("size は1以上にしてください")
    if not 0 <= overlap < size:
        raise ValueError("overlap は 0 以上 size 未満にしてください（無限ループを防ぐため）")
    if not text:
        return []

    step = size - overlap
    chunks: list[str] = []
    start = 0
    while True:
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            # 末尾まで届いたら打ち切る（届いたあとも step で進めると同じ末尾が二重に出る）
            break
        start += step
    return chunks


def sentence_windows(text: str, *, max_chars: int) -> list[str]:
    """文の境界を壊さずに、上限まで文を詰めていく（意味単位の分割）。

    Knowledge Bases の Semantic chunking と同じ狙いです（あちらは埋め込みの類似度で
    切れ目を決めますが、狙いは「1チャンクが単独で読める塊になること」で共通です）。
    1文だけで上限を超える場合は、その文に限って固定長へ落とします。
    """
    chunks: list[str] = []
    buffer = ""
    for sentence in split_sentences(text):
        if len(sentence) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(fixed_size(sentence, size=max_chars))
            continue
        if buffer and len(buffer) + len(sentence) > max_chars:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        chunks.append(buffer)
    return chunks


TITLE_TEMPLATE = "【{title}】{body}"


def with_title_prefix(title: str, chunks: list[str]) -> list[str]:
    """各チャンクの先頭に文書タイトルを付ける（階層構造の「親の見出し」を子に運ぶ）。

    固定長で切ると「に限り繰り越せますが、……」のように主語を失ったチャンクができます。
    タイトルを載せておくと、チャンク単独でも何の文書かが分かり、埋め込みにも
    文書の主題が入ります。列を増やせない索引でも使える、安価な階層化です。
    """
    return [TITLE_TEMPLATE.format(title=title, body=chunk) for chunk in chunks]


def to_rows(doc: dict, chunks: list[str]) -> list[dict]:
    """チャンクを `doc_chunks` の行に整える。メタデータは親文書から引き継ぐ。

    ここが「チャンクにしても出典を失わない」ための要点です。分割はコンテンツの操作で、
    メタデータの操作ではありません。分けた数だけ、同じ出典・分類・更新日を配ります。
    """
    return [
        {
            "doc_id": doc["id"],
            "chunk_index": index,
            "source_uri": doc["uri"],
            "title": doc["title"],
            "category": doc["category"],
            "updated_at": doc["updatedAt"],
            "content": chunk,
        }
        for index, chunk in enumerate(chunks)
    ]


def chunk_corpus(documents: list[dict], chunker, *, title_prefix: bool = False) -> list[dict]:
    """コーパス全体を1つの戦略で分けて、投入する行の一覧にする。

    `chunker` は「本文 → チャンクのリスト」の関数です。戦略を差し替えられる形に
    しておくと、あとで A/B を比べるときにパイプラインを書き換えずに済みます。
    """
    rows: list[dict] = []
    for doc in documents:
        chunks = chunker(doc["text"])
        if title_prefix:
            chunks = with_title_prefix(doc["title"], chunks)
        rows.extend(to_rows(doc, chunks))
    return rows


def fetch_parent(conn, doc_id: str) -> str:
    """子チャンクで当てて、親（文書全体）を返す（small-to-big）。

    検索は短いチャンクのほうが当たり、基盤モデルに渡す文脈は前後がつながって
    いるほうが答えやすい。この2つの要求は、当てるものと返すものを分けると両立します。
    重なりなしで投入した場合、連結すると元の本文に戻ります。
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content FROM doc_chunks WHERE doc_id = %s ORDER BY chunk_index",
            (doc_id,),
        )
        return "".join(row[0] for row in cur.fetchall())


def strategy_report(chunks: list[str], *, probe: str) -> dict:
    """分け方の性質を数える。`probe` は「丸ごと入っていてほしい文」。"""
    return {
        "count": len(chunks),
        "longest": max((len(c) for c in chunks), default=0),
        "cut_mid": sum(1 for c in chunks if not c.endswith(SENTENCE_END)),
        "has_probe": any(probe in c for c in chunks),
    }
