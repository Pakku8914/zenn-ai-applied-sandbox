"""読み取り結果の整合性検査（セッション7）。形は Pydantic で確かめ済みなので、ここでは「中身が筋の通った値か」を見る。

検査に落ちても結果は捨てない。issues に印を付けて needs_review にし、人に確かめてもらう。
issues の形はセッション4と同じ {index, name, reason, message}。レシート全体の問題は index・name を None にする。
"""

from __future__ import annotations

import re
from datetime import date

from src.session07.models import ReceiptRead

PRICE_MIN = 1          # 1行の金額の下限（円）。値引きの行（負の額）も人に見せる
PRICE_MAX = 100_000    # 1行の金額の上限（円）。食料品のレシートで10万円を超える行は読み違いを疑う
DATE_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MESSAGES = {
    "invalid_date": "購入日が YYYY-MM-DD の形でないか、ありえない日付（存在しない日・未来の日）です。日付を確かめてください",
    "total_mismatch": "明細の金額の合計と、合計金額が一致しません。金額を確かめてください",
    "price_out_of_range": f"金額が想定の範囲（{PRICE_MIN}〜{PRICE_MAX:,}円）を外れています。金額を確かめてください",
    "text_mismatch": "PDF に書かれた文字と読み取り結果が一致しません。レシートと見比べてください",
}


def issue(index: int | None, name: str | None, reason: str) -> dict:
    return {"index": index, "name": name, "reason": reason, "message": MESSAGES[reason]}


def valid_date(value: str, today: date) -> bool:
    if not DATE_FORMAT.match(value):  # fromisoformat は "20261001" も通すので、形は先に正規表現で決める
        return False
    try:
        day = date.fromisoformat(value)
    except ValueError:  # 2026-02-30 のような存在しない日
        return False
    return day <= today  # 未来に買い物はできない


def check_receipt(read: ReceiptRead, today: date) -> list[dict]:
    """日付 → 合計 → 各行の金額の順に調べ、見つかった問題をすべて返す（最初の1件で止めない）。"""
    issues: list[dict] = []
    if not valid_date(read.purchased_at, today):
        issues.append(issue(None, None, "invalid_date"))
    if sum(item.price for item in read.items) != read.total:
        issues.append(issue(None, None, "total_mismatch"))
    for index, item in enumerate(read.items):
        if not PRICE_MIN <= item.price <= PRICE_MAX:
            issues.append(issue(index, item.name, "price_out_of_range"))
    return issues
