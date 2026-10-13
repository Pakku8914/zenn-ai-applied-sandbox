"""マルチモーダルの評価で使う指標。CER（文字誤り率）は「正規化してから」比べる。"""

from __future__ import annotations

import re
import unicodedata

# 比較から外す文字：空白・句読点・括弧・記号（読み上げに現れないため）
_IGNORED = re.compile(r"[\s、。，．,.？?！!「」『』（）()・…~〜]")


def normalize_ja(text: str) -> str:
    """NFKC（全角英数→半角など）→ 小文字化 → 句読点・空白の除去。かなと漢字の表記ゆれは直さない。"""
    return _IGNORED.sub("", unicodedata.normalize("NFKC", text)).lower()


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """編集距離 ÷ 正解の文字数（どちらも normalize_ja したあと）。0.0 が完全一致。1.0 を超えることもある。"""
    ref, hyp = normalize_ja(reference), normalize_ja(hypothesis)
    return levenshtein(ref, hyp) / max(1, len(ref))
