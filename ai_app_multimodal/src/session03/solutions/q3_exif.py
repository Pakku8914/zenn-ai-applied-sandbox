"""問題3：画像の EXIF に何が入っているかを調べ、前処理で消えることを確かめる。

    docker compose exec api python -m src.session03.solutions.q3_exif
"""

from __future__ import annotations

import io

from PIL import Image

from kondate.media import media_path
from src.session03.images import prepare_image
from src.session03.make_variants import make_all

MAKE, ORIENTATION, GPS_IFD = 0x010F, 0x0112, 0x8825


def exif_report(raw: bytes) -> dict:
    with Image.open(io.BytesIO(raw)) as img:
        exif = img.getexif()
        return {
            "format": img.format,
            "size": img.size,
            "has_exif": len(exif) > 0,
            "has_gps": len(exif.get_ifd(GPS_IFD)) > 0,  # 位置情報は IFD0 ではなく GPS IFD に入っている
            "orientation": exif.get(ORIENTATION),
            "make": exif.get(MAKE),
        }


def yn(flag: bool) -> str:
    return "あり" if flag else "なし"


def show(label: str, r: dict) -> None:
    w, h = r["size"]
    print(f"{label}: {r['format']} {w}×{h} EXIF={yn(r['has_exif'])} GPS={yn(r['has_gps'])} "
          f"Orientation={r['orientation']} 機種={r['make']}")


def main() -> None:
    fridge = media_path("fridge.jpg").read_bytes()
    portrait = make_all()["portrait"].read_bytes()
    show("fridge.jpg", exif_report(fridge))
    show("fridge.jpg（前処理後）", exif_report(prepare_image(fridge).data))
    show("fridge_portrait.jpg", exif_report(portrait))
    show("fridge_portrait.jpg（前処理後）", exif_report(prepare_image(portrait).data))


if __name__ == "__main__":
    main()
