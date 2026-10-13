"""検証用の画像と PDF を決定的に生成する（実写・著作物は使わない）。

    python tools/make_media.py               # media/ に書き出す
    python tools/make_media.py --out DIR     # 別の場所に書き出す（ハッシュの再現確認用）
    python tools/make_media.py --check       # 書き出さずにハッシュだけ表示する

生成物（すべて data/recipes.json と固定の値だけから作る）：
- fridge.jpg            冷蔵庫の写真の代わりの合成画像 1280×960。EXIF にダミーの撮影日時・機種・位置情報（GPS）を入れてある
- receipt.png           レシートの写真の代わりの合成画像 600×900
- receipt.pdf           同じレシートの PDF（1ページ・テキスト付き）
- recipe_book.pdf       レシピ本の PDF（3ページ：肉じゃが・生姜焼き・みそ汁）
- recipe_book_full.pdf  レシピ本の PDF（120ページ：R001〜R120 を1ページずつ）

ハッシュはフォント（Debian の fonts-ipaexfont-gothic 00401-5）と Pillow・fpdf2 のバージョンに依存する。
api コンテナ（固定バージョン）の中で実行すること。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf"
FIXED_DATE = datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc)

# レシートの中身（mockllm の receipt シナリオと同じ値）
STORE = "こんだてマート"
PURCHASED_AT = "2026-10-01 18:42"
RECEIPT_ITEMS = [("鶏むね肉", 398), ("キャベツ", 198), ("卵（10個入り）", 248), ("牛乳", 228)]

# 冷蔵庫の中身（mockllm の fridge_photo シナリオと同じ5品）。(名前, 色, 形, 位置)
FRIDGE_ITEMS = [
    ("キャベツ", (120, 180, 90), "circle", (150, 200, 430, 420)),
    ("鶏むね肉", (235, 190, 175), "rect", (520, 250, 830, 400)),
    ("卵", (250, 245, 230), "eggs", (900, 230, 1180, 410)),
    ("にんじん", (235, 130, 50), "carrot", (180, 560, 560, 680)),
    ("牛乳", (245, 245, 250), "carton", (700, 500, 860, 840)),
]

# レシピ本（小）に載せるレシピ。mockllm の recipe_pdf シナリオの「1ページ＝肉じゃが・2ページ＝生姜焼き」とそろえる
SMALL_BOOK_IDS = ["R029", "R011", "R084"]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def _dms(value: float) -> tuple[float, float, float]:
    deg = int(value)
    minutes_f = (value - deg) * 60
    minutes = int(minutes_f)
    seconds = round((minutes_f - minutes) * 60, 2)
    return (float(deg), float(minutes), seconds)


def make_fridge(path: Path) -> None:
    img = Image.new("RGB", (1280, 960), (232, 238, 242))
    d = ImageDraw.Draw(img)
    # 庫内の棚と扉の縁
    d.rectangle((40, 40, 1240, 920), outline=(170, 180, 190), width=12)
    for y in (470, 880):
        d.rectangle((52, y, 1228, y + 14), fill=(200, 210, 218))
    for name, color, shape, (x0, y0, x1, y1) in FRIDGE_ITEMS:
        if shape == "circle":
            d.ellipse((x0, y0, x1, y1), fill=color, outline=(80, 130, 60), width=6)
            for i in range(1, 4):
                d.arc((x0 + i * 30, y0 + i * 20, x1 - i * 30, y1 - i * 20), 200, 340, fill=(90, 150, 70), width=4)
        elif shape == "rect":
            d.rounded_rectangle((x0, y0, x1, y1), radius=30, fill=color, outline=(190, 140, 130), width=5)
            d.rectangle((x0 - 10, y0 - 10, x1 + 10, y1 + 10), outline=(150, 150, 160), width=3)  # ラップのトレー
        elif shape == "eggs":
            for i in range(4):
                cx = x0 + 35 + i * 68
                d.ellipse((cx - 30, y0 + 40, cx + 30, y0 + 120), fill=color, outline=(200, 190, 170), width=3)
            d.rectangle((x0, y0 + 100, x1, y1), fill=(210, 200, 180))
        elif shape == "carrot":
            d.polygon([(x0, y0 + 60), (x1, y0 + 30), (x1, y0 + 90)], fill=color, outline=(190, 100, 40))
            d.line((x1, y0 + 60, x1 + 50, y0 + 20), fill=(70, 150, 60), width=10)
        elif shape == "carton":
            d.rectangle((x0, y0 + 60, x1, y1), fill=color, outline=(120, 140, 200), width=5)
            d.polygon([(x0, y0 + 60), ((x0 + x1) // 2, y0), (x1, y0 + 60)], fill=(220, 225, 240), outline=(120, 140, 200))
            d.text((x0 + 18, y0 + 160), "MILK", font=font(40), fill=(60, 90, 170))
        # 名札（読み取りの手がかり。実写ではないことが一目で分かるよう、あえて付けている）
        d.rounded_rectangle((x0, y1 + 8, x0 + 40 + 36 * len(name), y1 + 56), radius=10, fill=(255, 255, 255), outline=(90, 90, 90), width=2)
        d.text((x0 + 18, y1 + 12), name, font=font(34), fill=(30, 30, 30))
    d.text((60, 60), "こんだてAI 検証用の合成画像（実写ではありません）", font=font(26), fill=(110, 120, 130))

    exif = Image.Exif()
    exif[0x010F] = "KondateCam"                 # Make
    exif[0x0110] = "KC-1 (synthetic)"           # Model
    exif[0x0132] = "2026:10:01 18:30:00"        # DateTime
    gps = {
        1: "N", 2: _dms(35.681236),               # GPSLatitudeRef / GPSLatitude（ダミー：東京駅付近）
        3: "E", 4: _dms(139.767125),              # GPSLongitudeRef / GPSLongitude
    }
    exif[0x8825] = gps                          # GPSInfo IFD
    img.save(path, "JPEG", quality=85, exif=exif.tobytes())


def make_receipt_png(path: Path) -> None:
    img = Image.new("RGB", (600, 900), (252, 252, 248))
    d = ImageDraw.Draw(img)
    d.text((300, 60), STORE, font=font(40), fill=(20, 20, 20), anchor="mm")
    d.text((300, 110), "東京都こんだて区1-2-3（架空）", font=font(20), fill=(70, 70, 70), anchor="mm")
    d.text((60, 170), f"{PURCHASED_AT}", font=font(24), fill=(20, 20, 20))
    d.line((40, 215, 560, 215), fill=(120, 120, 120), width=2)
    y = 240
    for name, price in RECEIPT_ITEMS:
        d.text((60, y), name, font=font(28), fill=(20, 20, 20))
        d.text((540, y), f"¥{price:,}", font=font(28), fill=(20, 20, 20), anchor="ra")
        y += 60
    d.line((40, y + 10, 560, y + 10), fill=(120, 120, 120), width=2)
    total = sum(p for _, p in RECEIPT_ITEMS)
    d.text((60, y + 40), "合計", font=font(34), fill=(20, 20, 20))
    d.text((540, y + 40), f"¥{total:,}", font=font(34), fill=(20, 20, 20), anchor="ra")
    d.text((60, y + 110), f"点数 {len(RECEIPT_ITEMS)}点", font=font(22), fill=(60, 60, 60))
    d.text((300, 860), "検証用の合成レシート（架空の店舗）", font=font(18), fill=(130, 130, 130), anchor="mm")
    img.save(path, "PNG", optimize=False)


def _pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_creation_date(FIXED_DATE)
    pdf.set_creator("kondate make_media.py")
    pdf.set_producer("fpdf2")
    pdf.add_font("ipaexg", fname=FONT)
    pdf.set_font("ipaexg", size=12)
    pdf.set_auto_page_break(auto=True, margin=15)
    return pdf


def make_receipt_pdf(path: Path) -> None:
    pdf = _pdf()
    pdf.set_title(f"{STORE} レシート")
    pdf.add_page(format=(80, 160))
    pdf.set_margins(6, 8, 6)
    pdf.set_xy(6, 8)
    pdf.set_font("ipaexg", size=14)
    pdf.cell(0, 8, STORE, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=8)
    pdf.cell(0, 5, "東京都こんだて区1-2-3（架空）", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, PURCHASED_AT, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=10)
    for name, price in RECEIPT_ITEMS:
        pdf.cell(44, 7, name)
        pdf.cell(0, 7, f"¥{price:,}", align="R", new_x="LMARGIN", new_y="NEXT")
    total = sum(p for _, p in RECEIPT_ITEMS)
    pdf.set_font("ipaexg", size=12)
    pdf.cell(44, 9, "合計")
    pdf.cell(0, 9, f"¥{total:,}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=8)
    pdf.cell(0, 6, f"点数 {len(RECEIPT_ITEMS)}点", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "検証用の合成レシート（架空の店舗）", align="C")
    pdf.output(str(path))


def _recipe_page(pdf: FPDF, r: dict, page_no: int) -> None:
    pdf.add_page()
    pdf.set_font("ipaexg", size=20)
    pdf.multi_cell(0, 11, f"{r['name']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=10)
    pdf.cell(0, 7, f"{r['id']}　調理時間 {r['minutes']}分　{r['servings']}人分　1人分 {r['kcal']}kcal", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "タグ：" + "・".join(r["tags"]), new_x="LMARGIN", new_y="NEXT")
    allergens = "・".join(r["allergens"]) or "なし（7品目）"
    pdf.cell(0, 7, f"アレルゲン（特定原材料7品目）：{allergens}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("ipaexg", size=13)
    pdf.cell(0, 9, "材料", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=11)
    for ing in r["ingredients"]:
        amount = f"{ing['amount']:g}"
        pdf.cell(80, 7, f"・{ing['name']}")
        pdf.cell(0, 7, f"{amount} {ing['unit']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("ipaexg", size=13)
    pdf.cell(0, 9, "作り方", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("ipaexg", size=11)
    for i, step in enumerate(r["steps"], 1):
        pdf.multi_cell(0, 7, f"{i}. {step}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(-20)
    pdf.set_font("ipaexg", size=9)
    pdf.cell(0, 8, f"こんだてAI レシピ集（検証用・架空）　{page_no}", align="C")


def make_recipe_book(path: Path, ids: list[str] | None) -> None:
    recipes = json.loads((ROOT / "data" / "recipes.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in recipes}
    chosen = [by_id[i] for i in ids] if ids else recipes
    pdf = _pdf()
    pdf.set_title("こんだてAI レシピ集")
    pdf.set_auto_page_break(auto=False)
    for n, r in enumerate(chosen, 1):
        _recipe_page(pdf, r, n)
    pdf.output(str(path))


BUILDERS = {
    "fridge.jpg": make_fridge,
    "receipt.png": make_receipt_png,
    "receipt.pdf": make_receipt_pdf,
    "recipe_book.pdf": lambda p: make_recipe_book(p, SMALL_BOOK_IDS),
    "recipe_book_full.pdf": lambda p: make_recipe_book(p, None),
}


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "media"))
    ap.add_argument("--check", action="store_true", help="書き出さずにハッシュだけ表示する")
    args = ap.parse_args()
    if args.check:
        import tempfile
        out = Path(tempfile.mkdtemp())
    else:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, build in BUILDERS.items():
        build(out / name)
        result[name] = sha12(out / name)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
