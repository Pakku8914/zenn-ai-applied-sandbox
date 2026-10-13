"""問題4：表記ゆれの吸収を広げる（大匙・漢数字）。読み違い（番模範・は食・若目）は吸収しない。"""

from __future__ import annotations

from kondate.metrics import cer, levenshtein, normalize_ja
from src.session08.textnorm import VARIANTS, fold_kana

VARIANTS_EXT = {**VARIANTS, "大匙": "大さじ"}
_KANJI_DIGITS = str.maketrans("〇一二三四五六七八九", "0123456789")   # 1文字ずつの置き換え。「二十」は「2十」になり「20」とは一致しない


def normalize_relaxed_ext(text: str) -> str:
    out = fold_kana(normalize_ja(text)).translate(_KANJI_DIGITS)
    for src, dst in VARIANTS_EXT.items():
        out = out.replace(src, dst)
    return out


def cer_relaxed_ext(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize_relaxed_ext(reference), normalize_relaxed_ext(hypothesis)
    return levenshtein(ref, hyp) / max(1, len(ref))


PAIRS = [
    ("冷蔵庫に卵と牛乳とにんじんがあります。", "冷蔵庫に卵と牛乳とニンジンがあります"),
    ("鶏むね肉とキャベツで20分で作れる料理は？", "鶏胸肉とキャベツで20分で作れる料理は"),
    ("小麦を使わない晩ごはんを探して。", "小麦を使わない晩ご飯を探して"),
    ("小麦を使わない晩ごはんを探して。", "小麦を使わない番模範を探して"),
    ("今日は30分以内で作れる和食がいいな。", "今日は30分以内で作れるは食がいいな"),
    ("大さじ2杯は何ミリリットル？", "大匙2杯は何ミリリットル"),
    ("豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。", "豚こま切れ肉と玉ねぎの生姜焼きを四人分作りたい"),
]


def table() -> list[tuple[str, float, float]]:
    return [(hyp, round(cer(ref, hyp), 4), round(cer_relaxed_ext(ref, hyp), 4)) for ref, hyp in PAIRS]


if __name__ == "__main__":
    print("| 認識結果 | 厳密 | ゆれ吸収 |")
    print("| :-- | --: | --: |")
    for hyp, strict, relaxed in table():
        print(f"| {hyp} | {strict} | {relaxed} |")
