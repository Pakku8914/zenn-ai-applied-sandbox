"""検証用の画像・PDF（media/）。tools/make_media.py が決定的に生成する。実写・著作物は使わない。"""

from __future__ import annotations

from pathlib import Path

from kondate.settings import get_settings

# 生成物の SHA256 先頭12桁（api コンテナ＝固定バージョンのフォント・Pillow・fpdf2 で生成）
EXPECTED_SHA12 = {
    "fridge.jpg": "ee7fd20ff1e6",
    "receipt.png": "dbbc03c59a2f",
    "receipt.pdf": "2251bc149851",
    "recipe_book.pdf": "e92b4c3c93af",
    "recipe_book_full.pdf": "cb803f2fd448",
}


def media_path(name: str) -> Path:
    return Path(get_settings().media_dir) / name
