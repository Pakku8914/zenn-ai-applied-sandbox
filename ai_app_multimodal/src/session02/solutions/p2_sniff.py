"""問題2：受け付けない形式も名前で見分ける describe()。

    docker compose exec api python -m src.session02.solutions.p2_sniff
"""

from __future__ import annotations

import io
import wave
import zipfile

from PIL import Image
from pypdf import PdfWriter

ACCEPTED = {"JPEG", "PNG", "GIF", "WEBP", "PDF"}
SIGNATURES = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP"),  # Office 文書（.docx・.xlsx）も中身は ZIP
]
HEIF_BRANDS = {b"heic", b"heix", b"mif1"}  # iPhone の写真（HEIC）など


def sniff_any(raw: bytes) -> str | None:
    for magic, fmt in SIGNATURES:
        if raw.startswith(magic):
            return fmt
    if raw[:4] == b"RIFF":  # RIFF は入れ物の名前。中身の種類は 8〜11 バイト目に書いてある
        return {b"WEBP": "WEBP", b"WAVE": "WAV"}.get(raw[8:12])
    if raw[4:8] == b"ftyp" and raw[8:12] in HEIF_BRANDS:  # 先頭4バイトは箱の長さなので見ない
        return "HEIC"
    return None


def describe(raw: bytes) -> str:
    fmt = sniff_any(raw)
    if fmt is None:
        return "不明（受け付けない）"
    return f"{fmt}（{'受け付ける' if fmt in ACCEPTED else '受け付けない'}）"


def _image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, fmt)
    return buf.getvalue()


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("memo.txt", "買い物メモ")
    return buf.getvalue()


def samples() -> list[tuple[str, bytes]]:
    return [
        ("JPEG の画像", _image("JPEG")),
        ("PNG の画像", _image("PNG")),
        ("GIF の画像", _image("GIF")),
        ("WebP の画像", _image("WEBP")),
        ("PDF", _pdf()),
        ("WAV の音声", _wav()),
        ("HEIC の写真（先頭だけ）", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16),
        ("ZIP", _zip()),
        ("テキスト", "鶏むね肉 1枚".encode()),
    ]


def run() -> list[str]:
    return [f"{label} → {describe(raw)}" for label, raw in samples()]


if __name__ == "__main__":
    print("\n".join(run()))
