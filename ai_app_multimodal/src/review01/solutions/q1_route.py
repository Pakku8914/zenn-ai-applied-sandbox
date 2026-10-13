"""問題1：中身で受付を判定し、通った画像だけを前処理して画像トークンを見積もる。

    docker compose exec api python -m src.review01.solutions.q1_route
"""

from __future__ import annotations

from src.review01 import samples
from src.review01.kit import Rejected, estimate_image_tokens, inspect_upload, prepare_image


def route(raw: bytes) -> str:
    """名前も Content-Type も受け取らない。中身だけで判断する。"""
    try:
        kind, ext = inspect_upload(raw)  # セッション2：マジックバイト → 開けるか → 画素数・ページ数
    except Rejected as e:
        return f"{e.status} {e.type}「{e.message}」"
    head = f"受付 {kind}・拡張子 {ext}"
    if kind != "image":
        return f"{head} → 画像ではないので前処理しない"
    p = prepare_image(raw)  # セッション3：向き → RGB → 長辺 1568 まで縮小 → EXIF なしの JPEG
    w, h = p.sent_size
    return f"{head} → 送信 {w}×{h}・{estimate_image_tokens(w, h)} トークン"


def cases() -> list[tuple[str, bytes]]:
    # ラベルは表示のためだけ。route() にはファイル名を渡さない
    return [
        ("fridge.jpg", samples.fridge()),
        ("fridge.png（中身は JPEG）", samples.fridge()),
        ("memo.png（中身は文章）", samples.text_file()),
        ("broken.png（先頭だけ PNG）", samples.broken_png()),
        ("receipt.png", samples.receipt_png()),
        ("recipe_book.pdf", samples.recipe_pdf()),
    ]


def main() -> None:
    for label, raw in cases():
        print(f"{label} → {route(raw)}")


if __name__ == "__main__":
    main()
