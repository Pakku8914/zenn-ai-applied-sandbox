"""問題1：検証用のファイルの付帯情報に、個人情報の手がかりがあるかを調べる。

    docker compose exec api python -m src.session13.solutions.q1_inventory
"""

from __future__ import annotations

from kondate.media import media_path
from src.session13.images import prepare_image
from src.session13.privacy import image_findings, pdf_findings


def yn(flag: bool) -> str:
    return "あり" if flag else "なし"


def image_line(label: str, raw: bytes) -> str:
    f = image_findings(raw)
    return f"{label}: EXIF={yn(f['exif'])} GPS={yn(f['gps'])} 機種={yn(f['device'])} 撮影日時={yn(f['taken_at'])}"


def report() -> list[str]:
    fridge = media_path("fridge.jpg").read_bytes()
    pdf = pdf_findings(media_path("receipt.pdf").read_bytes())
    return [
        image_line("fridge.jpg", fridge),
        image_line("fridge.jpg（前処理後）", prepare_image(fridge).data),
        image_line("receipt.png", media_path("receipt.png").read_bytes()),
        f"receipt.pdf: タイトル={yn(pdf['title'])} 作成者={yn(pdf['author'])} 作成ソフト={yn(pdf['creator'])}",
    ]


if __name__ == "__main__":
    print("\n".join(report()))
