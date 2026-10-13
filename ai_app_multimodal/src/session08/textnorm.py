"""CER を比べる前に、表記ゆれをどこまでそろえるか。kondate.metrics.normalize_ja（NFKC・句読点・空白）の上に重ねる。"""

from __future__ import annotations

from kondate.metrics import levenshtein, normalize_ja

_KATA_TO_HIRA = {code: code - 0x60 for code in range(ord("ァ"), ord("ヶ") + 1)}

# 同じ語の書き方の違い（意味は同じ）。正解側・認識側の両方に同じ置き換えをかける。
# キーはカタカナをひらがなにした「後」の形で書く（カタカナのキーは決して一致しない）
VARIANTS = {
    "胸肉": "むね肉",
    "人参": "にんじん",
    "ご飯": "ごはん",
}


def fold_kana(text: str) -> str:
    """カタカナをひらがなにする（ニンジン → にんじん）。長音「ー」と中黒「・」はそのまま。"""
    return text.translate(_KATA_TO_HIRA)


def normalize_relaxed(text: str) -> str:
    out = fold_kana(normalize_ja(text))
    for src, dst in VARIANTS.items():
        out = out.replace(src, dst)
    return out


def cer_relaxed(reference: str, hypothesis: str) -> float:
    """表記ゆれを吸収した CER。読み違い（晩ごはん → 番模範）は吸収しない。"""
    ref, hyp = normalize_relaxed(reference), normalize_relaxed(hypothesis)
    return levenshtein(ref, hyp) / max(1, len(ref))
