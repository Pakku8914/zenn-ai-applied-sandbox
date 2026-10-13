"""表記ゆれをそろえる正規化（セッション12の textnorm.py の写し）。CER のゆれ吸収と、食材名の照合で使う。"""

from __future__ import annotations

from kondate.metrics import normalize_ja

_KATA_TO_HIRA = {code: code - 0x60 for code in range(ord("ァ"), ord("ヶ") + 1)}
VARIANTS = {
    "胸肉": "むね肉",
    "人参": "にんじん",
    "ご飯": "ごはん",
}


def fold_kana(text: str) -> str:
    return text.translate(_KATA_TO_HIRA)


def normalize_relaxed(text: str) -> str:
    out = fold_kana(normalize_ja(text))
    for src, dst in VARIANTS.items():
        out = out.replace(src, dst)
    return out
