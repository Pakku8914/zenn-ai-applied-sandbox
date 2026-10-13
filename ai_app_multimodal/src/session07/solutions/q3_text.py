"""問題3：PDF の文字から購入日・合計・金額を拾う規則を、いろいろなレシートの書き方に広げる。

本文の parse_receipt_text は receipt.pdf の書き方（2026-10-01・¥1,072）だけを読む。
ここでは「2026年10月1日」「2026/10/1」「1,072円」「合計 426円」も読めるようにする。

    docker compose exec api python -m src.session07.solutions.q3_text
"""

from __future__ import annotations

import re

from kondate.media import media_path
from src.session07.pdftext import ReceiptText, extract_text, nfkc, parse_receipt_text, squash, yen

AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)"
MONEY = r"(?:¥\s*" + AMOUNT + r"|" + AMOUNT + r"\s*円)"      # ¥1,072 か 1,072円（どちらか片方のグループに入る）
YEN = re.compile(MONEY)
TOTAL = re.compile(r"合計\s*" + MONEY)
DATE = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")


def first_group(groups: tuple[str, ...]) -> str:
    return next(g for g in groups if g)


def parse_receipt_text_v2(text: str) -> ReceiptText | None:
    t = nfkc(text)  # 全角の数字・￥・，・康熙部首はここでそろう
    if not squash(t):
        return None
    day = DATE.search(t)
    total = TOTAL.search(t)
    return ReceiptText(
        squashed=squash(t),
        purchased_at=f"{int(day[1]):04d}-{int(day[2]):02d}-{int(day[3]):02d}" if day else None,
        total=yen(first_group(total.groups())) if total else None,
        amounts=frozenset(yen(first_group(g)) for g in YEN.findall(t)),
    )


SAMPLES = {
    "receipt.pdf": None,  # 実物から抜き出す
    "全角と年月日": "こんだてマート\n2026年10月1日 18:42\n鶏むね⾁　￥３９８\n合計　￥３９８",
    "円で終わる金額": "2026/10/1\nキャベツ 198円\n牛乳 228円\n合計 426円",
    "文字なし": "",
}


def summarize(parsed: ReceiptText | None) -> tuple | None:
    return None if parsed is None else (parsed.purchased_at, parsed.total, sorted(parsed.amounts))


def results() -> dict[str, tuple[tuple | None, tuple | None]]:
    out = {}
    for label, text in SAMPLES.items():
        if text is None:
            text = extract_text(media_path("receipt.pdf").read_bytes())
        out[label] = (summarize(parse_receipt_text(text)), summarize(parse_receipt_text_v2(text)))
    return out


if __name__ == "__main__":
    for label, (before, after) in results().items():
        print(f"{label}: 本文の版 {before} → 広げた版 {after}")
    # receipt.pdf: 本文の版 ('2026-10-01', 1072, [198, 228, 248, 398, 1072]) → 広げた版 ('2026-10-01', 1072, [198, 228, 248, 398, 1072])
    # 全角と年月日: 本文の版 (None, 398, [398]) → 広げた版 ('2026-10-01', 398, [398])
    # 円で終わる金額: 本文の版 (None, None, []) → 広げた版 ('2026-10-01', 426, [198, 228, 426])
    # 文字なし: 本文の版 None → 広げた版 None
