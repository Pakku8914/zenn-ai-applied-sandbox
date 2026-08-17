"""チャンク分割の4方式（セッション4の主題）。

すべて (Doc, **params) -> list[Chunk] のシグネチャに揃えている。
"""

from __future__ import annotations

import re

from .models import Chunk, Doc

_SENT_END = re.compile(r"(?<=[。！？])")
_HEADING = re.compile(r"^#{1,4}\s*(.+)$", re.MULTILINE)


def _mk(doc: Doc, texts: list[str], method: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, t in enumerate(texts, start=1):
        t = t.strip()
        if not t:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}#{i:03d}",
                doc_id=doc.doc_id,
                text=t,
                ordinal=i,
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


def chunk_fixed(doc: Doc, size: int = 400, overlap: int = 80) -> list[Chunk]:
    """固定長分割。実装は簡単だが文や表の途中で切れる（境界問題）。"""
    if overlap >= size:
        raise ValueError("overlap は size より小さくすること")
    text = doc.full_text
    step = size - overlap
    parts = [text[i : i + size] for i in range(0, max(len(text), 1), step)]
    return _mk(doc, parts, "fixed")


def chunk_sentence(doc: Doc, max_chars: int = 400) -> list[Chunk]:
    """文境界で切り、max_chars に収まるまで文を束ねる。"""
    sents = [s for s in _SENT_END.split(doc.full_text) if s.strip()]
    parts: list[str] = []
    buf = ""
    for s in sents:
        if buf and len(buf) + len(s) > max_chars:
            parts.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        parts.append(buf)
    return _mk(doc, parts, "sentence")


def chunk_heading(doc: Doc, max_chars: int = 600) -> list[Chunk]:
    """見出し（Markdown の #）を意味単位として使う。見出しの無い文書では文境界に退避する。"""
    body = doc.body
    if not _HEADING.search(body):
        return _mk(doc, [c.text for c in chunk_sentence(doc, max_chars)], "heading")

    sections: list[str] = []
    last = 0
    starts = [m.start() for m in _HEADING.finditer(body)]
    for i, start in enumerate(starts):
        if i == 0 and start > 0:
            sections.append(body[:start])
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        sections.append(body[start:end])
        last = end
    if last < len(body):
        sections.append(body[last:])

    # 長すぎる節はさらに分割する（見出し単位が巨大な文書への保険）
    parts: list[str] = []
    for sec in sections:
        head = f"{doc.title}\n"
        if len(sec) <= max_chars:
            parts.append(head + sec)
        else:
            for i in range(0, len(sec), max_chars):
                parts.append(head + sec[i : i + max_chars])
    return _mk(doc, parts, "heading")


def chunk_parent_window(doc: Doc, child: int = 200, window: int = 600) -> list[Chunk]:
    """子チャンクで検索し、親（前後を含む広い範囲）を回答に使う方式。

    meta["parent_text"] に親を入れる。検索単位と回答単位を分離するのが狙い。
    """
    text = doc.full_text
    chunks = _mk(doc, [text[i : i + child] for i in range(0, max(len(text), 1), child)], "parent_window")
    out: list[Chunk] = []
    for c in chunks:
        center = (c.ordinal - 1) * child + child // 2
        start = max(0, center - window // 2)
        parent = text[start : start + window]
        out.append(Chunk(c.chunk_id, c.doc_id, c.text, c.ordinal, {**c.meta, "parent_text": parent}))
    return out


CHUNKERS = {
    "fixed": chunk_fixed,
    "sentence": chunk_sentence,
    "heading": chunk_heading,
    "parent_window": chunk_parent_window,
}


def chunk_all(docs: list[Doc], method: str = "fixed", **params) -> list[Chunk]:
    if method not in CHUNKERS:
        raise ValueError(f"unknown method: {method} (available: {list(CHUNKERS)})")
    fn = CHUNKERS[method]
    out: list[Chunk] = []
    for d in docs:
        out.extend(fn(d, **params))
    return out
