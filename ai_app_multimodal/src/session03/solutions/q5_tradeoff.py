"""問題5：長辺の上限を変えて、トークン・ファイルの大きさ・文字の大きさ・復元誤差がどう変わるかを表にする。

    docker compose exec api python -m src.session03.solutions.q5_tradeoff
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageStat

from kondate.media import media_path
from src.session03.images import prepare_image
from src.session03.make_variants import make_all

EDGES = (2576, 1568, 1024, 768, 512, 256)
LABEL_FONT_PX = 34    # 名札の文字の大きさ（fridge.jpg＝長辺 1280px のとき。tools/make_media.py の font(34)）
BASE_LONG_EDGE = 1280


def readability(font_px: int) -> str:
    """本書の演習用の目安：20px 以上＝◯、12〜19px＝△、それ未満＝×。"""
    return "◯" if font_px >= 20 else "△" if font_px >= 12 else "×"


def restore_error(sent: bytes, reference: Image.Image) -> float:
    """送る画像を元の大きさに戻し、元の画像との平均の差（0〜255）を測る。縮めて失った細部ほど大きくなる。"""
    with Image.open(io.BytesIO(sent)) as img:
        back = img.convert("L").resize(reference.size, Image.Resampling.BICUBIC)
    return ImageStat.Stat(ImageChops.difference(back, reference)).mean[0]


def tradeoff(raw: bytes) -> list[dict]:
    with Image.open(media_path("fridge.jpg")) as ref:
        reference = ref.convert("L")
    rows = []
    for edge in EDGES:
        p = prepare_image(raw, max_long_edge=edge)
        font_px = round(LABEL_FONT_PX * max(p.sent_size) / BASE_LONG_EDGE)
        rows.append({"edge": edge, "size": p.sent_size, "tokens": p.tokens, "bytes": len(p.data),
                     "font_px": font_px, "readable": readability(font_px), "error": restore_error(p.data, reference)})
    return rows


def main() -> None:
    raw = make_all()["large"].read_bytes()
    for r in tradeoff(raw):
        w, h = r["size"]
        print(f"長辺 {r['edge']:>4}: 送信 {w}×{h} ／ 画像トークン {r['tokens']:>4} ／ 名札の文字 約{r['font_px']}px {r['readable']}")


if __name__ == "__main__":
    main()
