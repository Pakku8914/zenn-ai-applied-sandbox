"""読み上げ用の文分割（セッション11の sentences.py の写し。セッション9から規則は変えていない）。

- Markdown の記号は読み上げ前に除く（見出し・箇条書き・番号付きリスト・引用・強調・コード・表の区切り・リンク）
- 「。」「？」「！」と改行で文に区切る。区切りの記号は文の末尾に残す
- 読む文字（文字・数字）が1つも残らない断片は捨てる
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*```")
_HEAD = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"\*\*|__|~~|[*`]")
_RULE = re.compile(r"(?:[-*_]\s*){3,}")
_SENTENCE = re.compile(r"[^。？！]+[。？！]*")
_SPEAKABLE = re.compile(r"[^\W_]")


def strip_markdown(line: str) -> str:
    if _FENCE.match(line):
        return ""
    line = _HEAD.sub("", line)
    line = _LINK.sub(r"\1", line)
    line = _EMPHASIS.sub("", line).replace("|", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return "" if _RULE.fullmatch(line) else line


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for line in text.splitlines():
        for piece in _SENTENCE.findall(strip_markdown(line)):
            piece = piece.strip()
            if _SPEAKABLE.search(piece):
                sentences.append(piece)
    return sentences
