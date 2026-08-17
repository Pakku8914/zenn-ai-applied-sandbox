"""日本語トークナイズ（レキシカル検索用）。

形態素解析（janome）と文字 bi-gram の2方式を持つ。両者の得失はセッション5の主題。
MeCab 系はネイティブビルドが必要で Windows/Mac 両対応が崩れるため採用していない。
"""

from __future__ import annotations

import re
import unicodedata

from janome.tokenizer import Tokenizer

_tokenizer = Tokenizer()

# 内容語だけを残す。助詞・助動詞・記号はノイズになるため落とす
_KEEP_POS = ("名詞", "動詞", "形容詞", "副詞")

_STOPWORDS = {"こと", "もの", "ため", "場合", "とき", "以下", "以上", "する", "ある", "なる", "いる"}


def normalize(text: str) -> str:
    """NFKC 正規化＋小文字化＋空白の畳み込み。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def tokens_morph(text: str) -> list[str]:
    """形態素解析による内容語の列。"""
    out: list[str] = []
    for token in _tokenizer.tokenize(normalize(text)):
        pos = token.part_of_speech.split(",")[0]
        if pos not in _KEEP_POS:
            continue
        surface = token.base_form if token.base_form != "*" else token.surface
        if len(surface) == 1 and re.fullmatch(r"[ぁ-んァ-ヶー]", surface):
            continue  # 1文字のかなは情報量が乏しい
        if surface in _STOPWORDS:
            continue
        out.append(surface)
    return out


def tokens_bigram(text: str) -> list[str]:
    """文字 bi-gram。未知語・型番・略語に強い代わりにノイズが増える。"""
    s = re.sub(r"[^0-9a-zぁ-んァ-ヶー一-龥]", "", normalize(text))
    return [s[i : i + 2] for i in range(len(s) - 1)] or ([s] if s else [])


def tokenize(text: str, mode: str = "morph") -> list[str]:
    """mode: "morph" / "bigram" / "morph+bigram"。"""
    if mode == "morph":
        return tokens_morph(text)
    if mode == "bigram":
        return tokens_bigram(text)
    if mode == "morph+bigram":
        return tokens_morph(text) + tokens_bigram(text)
    raise ValueError(f"unknown mode: {mode}")
