#!/usr/bin/env python3
"""セッション4：チャンクの後処理ユーティリティ。

`ragkit/chunk.py` の4方式は「文書をどう切るか」までを受け持つ。
現場ではそのあとに必ず次の後処理が必要になる。

  merge_adjacent       同一文書の連続チャンクを1つに畳む（重複ヒットの排除）
  parent_passages      子チャンクのヒットを親テキストに置き換える（検索単位 ≠ 回答単位）
  fit_budget           文字数の予算に収まるまで詰める
  chunk_heading_merged 小さすぎる見出し節を直前の節に併合する

いずれも「切り方」を変えずに効く後処理なので、方式を選び直すより先に試す価値がある。
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_heading  # noqa: E402
from ragkit.eval import hits_to_docs  # noqa: E402
from ragkit.models import Chunk, Doc, Hit  # noqa: E402


@dataclass(frozen=True)
class Passage:
    """生成に渡す単位。検索の単位（Chunk / Hit）とはあえて別の型にしている。

    1つの Passage が複数のチャンクから作られることがあるため、
    chunk_ids は tuple で保持する（あとから引用を検証するのに使う）。
    """

    doc_id: str
    title: str
    text: str
    score: float
    chunk_ids: tuple[str, ...]


# --- 切り方（固定長の最小実装）---------------------------------------------


def fixed_chunks(text: str, size: int = 400, overlap: int = 80) -> list[str]:
    """固定長で切る。ragkit.chunk.chunk_fixed と同じ切り方の最小実装。"""
    if overlap >= size:
        raise ValueError("overlap は size より小さくすること（同じ位置を切り続けてしまう）")
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text), 1), step)]


# --- 重なりの除去と畳み込み --------------------------------------------------


def overlap_len(a: str, b: str, max_overlap: int = 200) -> int:
    """a の末尾と b の先頭が重なっている長さ（最長一致）。重なりが無ければ 0。"""
    limit = min(len(a), len(b), max_overlap)
    for n in range(limit, 0, -1):
        if a.endswith(b[:n]):
            return n
    return 0


def join_without_overlap(a: str, b: str, max_overlap: int = 200) -> str:
    """重なりを1回だけ残して連結する。"""
    return a + b[overlap_len(a, b, max_overlap) :]


def ordinal_of(chunk_id: str) -> int:
    """チャンクIDから連番を取り出す（"DOC-0001#003" なら 3）。"""
    return int(chunk_id.rsplit("#", 1)[-1])


def merge_adjacent(hits: list[Hit], max_gap: int = 1, max_overlap: int = 200) -> list[Passage]:
    """同一文書のヒットを1つの Passage に畳む。

    連番が隣接している（差が max_gap 以内）チャンクは本文もつなぎ、
    オーバーラップで二重になった文字列を1回に戻す。
    離れている場合は「(中略)」を挟み、飛んでいることを生成側に伝える。
    """
    groups: dict[str, list[Hit]] = {}
    for hit in hits:
        groups.setdefault(hit.doc_id, []).append(hit)

    passages: list[Passage] = []
    for doc_id, found in groups.items():
        items = sorted(found, key=lambda h: ordinal_of(h.chunk_id))
        text = items[0].text
        previous = ordinal_of(items[0].chunk_id)
        for item in items[1:]:
            current = ordinal_of(item.chunk_id)
            if current - previous <= max_gap:
                text = join_without_overlap(text, item.text, max_overlap)
            else:
                text = f"{text}\n(中略)\n{item.text}"
            previous = current
        passages.append(
            Passage(
                doc_id=doc_id,
                title=str(items[0].meta.get("title", "")),
                text=text,
                # 文書のスコアは所属チャンクの最大値を採る（合計にすると長い文書が有利になる）
                score=max(h.score for h in items),
                chunk_ids=tuple(h.chunk_id for h in items),
            )
        )
    passages.sort(key=lambda p: -p.score)
    return passages


def parent_passages(hits: list[Hit]) -> list[Passage]:
    """子チャンクのヒットを、親テキスト（meta["parent_text"]）に置き換える。

    親を持たない方式のヒットでは、子の本文をそのまま使う。
    """
    passages: list[Passage] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.doc_id in seen:
            continue
        seen.add(hit.doc_id)
        passages.append(
            Passage(
                doc_id=hit.doc_id,
                title=str(hit.meta.get("title", "")),
                text=str(hit.meta.get("parent_text") or hit.text),
                score=hit.score,
                chunk_ids=(hit.chunk_id,),
            )
        )
    return passages


def fit_budget(passages: list[Passage], budget: int = 1200) -> list[Passage]:
    """文字数の予算に収まるものだけを先頭から採る。

    予算を超えるものは飛ばして次を見る（順位が下でも短ければ入る）。
    先頭が単体で予算を超える場合だけは、空のコンテキストを返さないよう切り詰める。
    """
    out: list[Passage] = []
    total = 0
    for passage in passages:
        if total + len(passage.text) <= budget:
            out.append(passage)
            total += len(passage.text)
        elif not out:
            out.append(replace(passage, text=passage.text[:budget]))
            total = budget
    return out


def build_context(hits: list[Hit], budget: int = 1200, use_parent: bool = False,
                  max_overlap: int = 200) -> list[Passage]:
    """検索結果を、生成に渡せる形（Passage の列）に整える。"""
    passages = (parent_passages(hits) if use_parent
                else merge_adjacent(hits, max_overlap=max_overlap))
    return fit_budget(passages, budget)


# --- 見出し分割の改良 --------------------------------------------------------


def to_chunks(doc: Doc, parts: list[str], method: str) -> list[Chunk]:
    """テキストの配列を Chunk に詰め直す（チャンクIDの規約は ragkit と同じ）。"""
    chunks: list[Chunk] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        ordinal = len(chunks) + 1
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}#{ordinal:03d}",
                doc_id=doc.doc_id,
                text=text,
                ordinal=ordinal,
                meta={
                    "title": doc.title,
                    "category": doc.category,
                    "updated_at": doc.updated_at,
                    "visibility": doc.visibility,
                    "dept": doc.dept,
                    "source_type": doc.source_type,
                    "method": method,
                },
            )
        )
    return chunks


def chunk_heading_merged(doc: Doc, max_chars: int = 600, min_chars: int = 200) -> list[Chunk]:
    """見出し分割の改良版：min_chars に満たない節を直前の節に併合する。

    ragkit.chunk.chunk_heading は節ごとに文書タイトルを前置するため、
    併合するときは2つ目以降のタイトルを落とす（同じ行を二重に持ち込まない）。
    """
    head = doc.title
    parts: list[str] = []
    for chunk in chunk_heading(doc, max_chars):
        section = (chunk.text[len(head):].lstrip("\n")
                   if chunk.text.startswith(head) else chunk.text)
        if parts and len(parts[-1]) < min_chars and len(parts[-1]) + len(section) + 1 <= max_chars:
            parts[-1] = f"{parts[-1]}\n{section}"
        else:
            parts.append(f"{head}\n{section}")
    return to_chunks(doc, parts, "heading_merged")


# --- 診断 --------------------------------------------------------------------


def mean_folded_docs(index, queries, qrels, k: int = 10) -> float:
    """上位k件のチャンクが平均して何文書に畳み込まれるかを測る。

    値が小さいほど「同じ文書のチャンクが上位を占めている」ことを意味する。
    Recall（拾えた文書の多様性）が落ちるだけでなく、Precision@k の分母も
    小さくなるため、方式をまたいで P@k を素朴に比べると読み違える。
    """
    counts: list[int] = []
    for query in queries:
        if not any(g >= 1 for g in qrels.get(query.query_id, {}).values()):
            continue  # 回答不能クエリは ragkit.eval.evaluate と同じ基準で除外する
        counts.append(len(hits_to_docs(index.search(query.text, k=k))))
    return statistics.mean(counts) if counts else 0.0
