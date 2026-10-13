"""演習用の画像を fridge.jpg から作り、out/s03/ に書き出す。

    docker compose exec api python -m src.session03.make_variants
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from kondate.media import media_path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "s03"
ORIENTATION = 0x0112  # EXIF の Orientation タグ


def make_large(src: Path, dst: Path) -> None:
    """高画素のスマホで撮ったつもりの 4000×3000 版。EXIF（位置情報を含む）はそのまま引き継ぐ。"""
    with Image.open(src) as img:
        exif = img.getexif()
        big = img.resize((4000, 3000), Image.Resampling.LANCZOS)
    big.save(dst, "JPEG", quality=85, exif=exif)


def make_portrait(src: Path, dst: Path) -> None:
    """画素は横倒しで保存し、向きは EXIF で伝える写真（スマホでよくある形）。Orientation=6＝表示するときに右へ90°回す。"""
    with Image.open(src) as img:
        exif = img.getexif()
        stored = img.transpose(Image.Transpose.ROTATE_90)  # 左へ90°倒した画素を保存する（960×1280）
    exif[ORIENTATION] = 6
    stored.save(dst, "JPEG", quality=85, exif=exif)


def make_all() -> dict[str, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    src = media_path("fridge.jpg")
    paths = {"large": OUT / "fridge_4000x3000.jpg", "portrait": OUT / "fridge_portrait.jpg"}
    make_large(src, paths["large"])
    make_portrait(src, paths["portrait"])
    return paths


if __name__ == "__main__":
    for path in make_all().values():
        with Image.open(path) as img:
            w, h = img.size
            exif = img.getexif()
            gps = "あり" if exif.get_ifd(0x8825) else "なし"
            orient = exif.get(ORIENTATION, "なし")
        print(f"{path.relative_to(ROOT)}  保存 {w}×{h}・Orientation={orient}・位置情報（GPS）{gps}")
