"""問題3：レシートの読み違い（FakeProvider）を要確認に回し、冷蔵庫の要確認（セッション4）と同じ形で要約する。

    docker compose exec api python -m src.review02.solutions.q3_review
"""

from __future__ import annotations

import asyncio

from kondate.clock import FixedClock
from kondate.llm import ChatResult, FakeProvider, Usage
from src.review02 import samples
from src.review02.kit import (
    Ingredient, accept_receipt, check_receipt, compare_with_text, find_issues, parse_receipt_text, read_receipt,
)

TODAY = FixedClock().now().date()  # 2026-10-02
USAGE = {"image": Usage(778, 104), "pdf": Usage(1652, 104)}


def where(i: dict) -> str:
    return "全体" if i["index"] is None else f"{i['index']} {i['name']}"


def summarize(issues: list[dict]) -> str:
    """セッション4（食材）とセッション7（レシート）の issues のどちらにも使える。"""
    return "、".join(f"{i['reason']}({where(i)})" for i in issues) or "なし"


async def read_and_review(raw: bytes, answer: str) -> tuple[list[dict], int]:
    accepted = accept_receipt(raw)
    fake = FakeProvider([ChatResult(answer, [], "end_turn", USAGE[accepted.kind])])
    result = await read_receipt(fake, accepted.kind, accepted.data)
    issues = check_receipt(result.receipt, TODAY)  # 中身の筋が通っているか
    if (text := parse_receipt_text(accepted.pdf_text)) is not None:  # 文字のある PDF だけ
        issues += compare_with_text(result.receipt, text)
    return issues, result.attempts


def fridge() -> list[Ingredient]:
    def ing(name: str, confidence: float) -> Ingredient:
        return Ingredient(name=name, quantity="1個", amount=1, unit="個", confidence=confidence, category="野菜")
    return [ing("キャベツ", 0.94), ing("鶏ムネ肉", 0.9), ing("にんじん", 0.42)]


async def run() -> None:
    png, pdf = samples.receipt_png(), samples.receipt_pdf()
    cases = [
        ("合計が合わない（画像）", png, samples.receipt_json(total=1000)),
        ("合計が合わない（PDF）", pdf, samples.receipt_json(total=1000)),
        ("つじつまの合う読み違い（画像）", png, samples.receipt_json(total=1063, prices={1: 189})),
        ("つじつまの合う読み違い（PDF）", pdf, samples.receipt_json(total=1063, prices={1: 189})),
        ("牛乳が 0 円（画像）", png, samples.receipt_json(total=844, prices={3: 0})),
        ("未来の日付（PDF）", pdf, samples.receipt_json(purchased_at="2026-10-03")),
    ]
    for label, raw, answer in cases:
        issues, attempts = await read_and_review(raw, answer)
        print(f"{label} → needs_review={bool(issues)}・{summarize(issues)}・試行 {attempts} 回")
    issues = find_issues(fridge())
    print(f"冷蔵庫の食材（セッション4） → needs_review={bool(issues)}・{summarize(issues)}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
