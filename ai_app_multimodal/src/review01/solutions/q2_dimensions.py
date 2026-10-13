"""問題2：画素数・向き・大きさの違う写真を流し、受付と前処理がそれぞれ何をするかを確かめる。

    docker compose exec api python -m src.review01.solutions.q2_dimensions
"""

from __future__ import annotations

from src.review01 import samples
from src.review01.kit import Rejected, estimate_image_tokens, inspect_upload, prepare_image


def size(wh: tuple[int, int]) -> str:
    return f"{wh[0]}×{wh[1]}"


def describe(raw: bytes) -> str:
    try:
        inspect_upload(raw)  # セッション2：画素数はヘッダーだけで調べる。展開する前に断る
    except Rejected as e:
        return f"{e.status} {e.type}「{e.message}」"
    p = prepare_image(raw)  # セッション3
    exif = "EXIF を除去" if p.exif_removed else "EXIF なし"
    as_is = estimate_image_tokens(*p.stored_size)  # 前処理せずに送ると、保存された画素の寸法で数えられる
    return (f"保存 {size(p.stored_size)}・向きを直して {size(p.original_size)}・送信 {size(p.sent_size)}・"
            f"{exif}・{p.tokens} トークン（前処理なし {as_is}）")


def cases() -> list[tuple[str, bytes]]:
    return [
        ("8000×6000 の PNG", samples.huge_png()),
        ("縦向きの写真", samples.portrait()),
        ("4000×3000 の写真", samples.large()),
        ("fridge.jpg", samples.fridge()),
    ]


def main() -> None:
    for label, raw in cases():
        print(f"{label} → {describe(raw)}")


if __name__ == "__main__":
    main()

# 縦向きの写真は、前処理してもしなくても画像トークンは 1610 で同じ。それでも前処理が要る理由：
# 1. 向き：画素は横倒しのまま保存されている。Orientation の指示が API で解釈される保証はないので、
#    回しておかないとモデルは横倒しの冷蔵庫を読むことになる（トークンではなく読み取りの精度に効く）
# 2. 位置情報：元の写真の EXIF には撮影場所（GPS）がある。作り直した JPEG には EXIF が残らない
