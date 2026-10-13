"""問題4：Orientation 1〜8 のどれで保存された写真も、前処理で正しい向きに戻ることを確かめる。

    docker compose exec api python -m src.session03.solutions.q4_orientation
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageStat

from kondate.media import media_path
from src.session03.images import prepare_image

T = Image.Transpose
# 「正しい向きの画像」をカメラが保存した画素に戻す変換（exif_transpose が行う変換の逆）
TO_STORED = {
    1: None, 2: T.FLIP_LEFT_RIGHT, 3: T.ROTATE_180, 4: T.FLIP_TOP_BOTTOM,
    5: T.TRANSPOSE, 6: T.ROTATE_90, 7: T.TRANSVERSE, 8: T.ROTATE_270,
}
MAX_DIFF = 8.0  # 向きが合っていれば JPEG の劣化分しか差が出ない（本書の目安）


def make_oriented(upright: Image.Image, orientation: int) -> bytes:
    method = TO_STORED[orientation]
    stored = upright if method is None else upright.transpose(method)
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    stored.save(buf, "JPEG", quality=90, exif=exif)
    return buf.getvalue()


def mean_diff(a: bytes, b: bytes) -> float:
    with Image.open(io.BytesIO(a)) as x, Image.open(io.BytesIO(b)) as y:
        if x.size != y.size:
            return 255.0  # 縦横が違う＝向きが戻っていない
        gx, gy = x.convert("L").resize((320, 240)), y.convert("L").resize((320, 240))
    return ImageStat.Stat(ImageChops.difference(gx, gy)).mean[0]


def check_all() -> list[dict]:
    reference = media_path("fridge.jpg").read_bytes()
    with Image.open(io.BytesIO(reference)) as img:
        upright = img.convert("RGB")
    rows = []
    for o in TO_STORED:
        p = prepare_image(make_oriented(upright, o))
        rows.append({"orientation": o, "stored": p.stored_size, "sent": p.sent_size,
                     "ok": mean_diff(p.data, reference) < MAX_DIFF})
    return rows


def main() -> None:
    for r in check_all():
        (sw, sh), (tw, th) = r["stored"], r["sent"]
        print(f"Orientation={r['orientation']}: 保存 {sw}×{sh} → 送信 {tw}×{th} ／ 元の向き: {'一致' if r['ok'] else '不一致'}")


if __name__ == "__main__":
    main()
