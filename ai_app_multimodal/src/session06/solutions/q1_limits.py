"""問題1：送る前に、上限と見積もりから「このまま送れるか」を判定する。

    docker compose exec api python -m src.session06.solutions.q1_limits
"""

from __future__ import annotations

import math

APP_MAX_BYTES = 10 * 1024 * 1024    # 受付の上限（セッション2）
APP_MAX_PAGES = 200                 # 受付の上限（セッション2）
API_MAX_REQUEST_BYTES = 32_000_000  # API のリクエスト全体（32MB を小さい方の 10 進で）
API_MAX_PAGES = 600                 # API の PDF の上限
TOKENS_PER_PAGE = 1600              # mockllm の式
CASES = [(3, 300_000), (120, 1_000_000), (201, 1_000_000), (650, 9_000_000), (150, 25_000_000)]


def base64_size(n: int) -> int:
    return 4 * math.ceil(n / 3)


def assess(pages: int, raw_bytes: int) -> list[str]:
    """引っかかる上限の名前を、決まった順で返す（空なら送れる）。"""
    codes = []
    if raw_bytes > APP_MAX_BYTES:
        codes.append("app_bytes")
    if pages > APP_MAX_PAGES:
        codes.append("app_pages")
    if base64_size(raw_bytes) > API_MAX_REQUEST_BYTES:  # 送るのは base64 にした後の大きさ
        codes.append("api_request")
    if pages > API_MAX_PAGES:
        codes.append("api_pages")
    return codes


def pages_within(budget_tokens: int) -> int:
    """1回の入力の予算に収まるページ数。"""
    return budget_tokens // TOKENS_PER_PAGE


def describe(pages: int, raw_bytes: int) -> str:
    codes = assess(pages, raw_bytes)
    verdict = "・".join(codes) if codes else "送れる"
    return (f"{pages}ページ・{raw_bytes:,}バイト → base64 {base64_size(raw_bytes):,}バイト・"
            f"見積もり {pages * TOKENS_PER_PAGE:,}トークン：{verdict}")


def main() -> None:
    for pages, raw_bytes in CASES:
        print(describe(pages, raw_bytes))
    print(f"予算 50,000 トークンで送れるのは {pages_within(50_000)} ページまで")


if __name__ == "__main__":
    main()
