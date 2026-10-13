"""セッション2の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session02/verify.py

アプリは httpx2.ASGITransport で同じプロセスに載せる（api の APP_MODULE を切り替えなくてよい）。
偽装したファイル・画素数の多い画像・ページ数の多い PDF は、ここでコードで作る（ファイルを追加しない）。
保存先は out/s02/uploads/ に差し替える。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import shutil
from pathlib import Path

import httpx2
from PIL import Image
from pypdf import PdfWriter

from kondate import media
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session02.app import MAX_PDF_PAGES, app, upload_dir

OUT = Path("out/s02")
UPLOADS = OUT / "uploads"
LIMIT = get_settings().upload_max_bytes
UPLOAD_ID = re.compile(r"^up_[0-9A-HJKMNP-TV-Z]{26}$")  # ULID は Crockford の Base32 で26文字
MSG_UNSUPPORTED = "JPEG・PNG・WebP・GIF の画像か PDF を送ってください"

logging.getLogger("pypdf").setLevel(logging.ERROR)  # 壊れた PDF を読ませたときの警告で出力が乱れないように
shutil.rmtree(OUT, ignore_errors=True)
app.dependency_overrides[upload_dir] = lambda: UPLOADS


def post(name: str, content: bytes, content_type: str, field: str = "file") -> httpx2.Response:
    async def run() -> httpx2.Response:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as c:
            return await c.post("/api/uploads", files={field: (name, content, content_type)})
    return asyncio.run(run())


def image_bytes(fmt: str, size: tuple[int, int] = (4, 4), mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, fmt)
    return buf.getvalue()


def pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def accepted(r: httpx2.Response, raw: bytes, kind: str, ext: str) -> str:
    eq(r.status_code, 201, f"status（本文 {r.text}）")
    body = r.json()
    eq(sorted(body), ["bytes", "kind", "sha256", "upload_id"], "応答の項目")
    assert UPLOAD_ID.match(body["upload_id"]), body["upload_id"]
    eq((body["kind"], body["bytes"], body["sha256"]), (kind, len(raw), hashlib.sha256(raw).hexdigest()), "kind・bytes・sha256")
    saved = UPLOADS / f"{body['upload_id']}.{ext}"
    eq(saved.read_bytes() == raw, True, f"{saved} の中身が送ったバイト列と同じ")
    return body["upload_id"]


def rejected(r: httpx2.Response, status: int, type_: str, message: str) -> None:
    eq(r.status_code, status, f"status（本文 {r.text}）")
    err = r.json()["error"]
    eq((err["type"], err["message"]), (type_, message), "エラー本文")
    eq(err["request_id"], r.headers["x-request-id"], "request_id がヘッダーと同じ")


@check("V1 検証用の写真・レシート画像・PDF を受け付け、中身で決めた拡張子で保存する")
def _():
    cases = [
        ("fridge.jpg", "image/jpeg", "image", "jpg"),
        ("receipt.png", "image/png", "image", "png"),
        ("receipt.pdf", "application/pdf", "pdf", "pdf"),
    ]
    for name, ctype, kind, ext in cases:
        raw = media.media_path(name).read_bytes()
        accepted(post(name, raw, ctype), raw, kind, ext)
    return "・".join(f"{n}→{k}/.{e}" for n, _, k, e in cases)


@check("V2 WebP・GIF を含む4形式の画像を、Pillow が判定した形式の拡張子で保存する")
def _():
    pairs = [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("GIF", "gif")]
    for fmt, ext in pairs:
        raw = image_bytes(fmt)
        accepted(post("upload.bin", raw, "application/octet-stream"), raw, "image", ext)
    return "・".join(f"{f}→.{e}" for f, e in pairs)


@check("V3 名前と Content-Type を偽っても、中身で決まる")
def _():
    png = media.media_path("receipt.png").read_bytes()
    accepted(post("receipt.pdf", png, "application/pdf"), png, "image", "png")
    text = "鶏むね肉 1枚\nキャベツ 1/2玉\n".encode()
    rejected(post("photo.jpg", text, "image/jpeg"), 415, "unsupported_media", MSG_UNSUPPORTED)
    return "PDF を名乗る PNG→image/.png・JPEG を名乗るテキスト→415"


@check("V4 先頭のバイトだけ本物に似せた偽物は、Pillow・pypdf で開けないので 415")
def _():
    fakes = [
        b"\x89PNG\r\n\x1a\n" + "これは画像ではありません".encode(),
        b"%PDF-1.7\n" + "これは PDF ではありません\n".encode() * 20,
    ]
    for raw in fakes:
        rejected(post("upload.bin", raw, "application/octet-stream"), 415, "unsupported_media", MSG_UNSUPPORTED)
    return "PNG の署名＋テキスト→415・%PDF-＋テキスト→415"


@check("V5 ちょうど 10MiB は大きさの検査を通り、1バイト多いと 413")
def _():
    rejected(post("big.jpg", b"x" * LIMIT, "image/jpeg"), 415, "unsupported_media", MSG_UNSUPPORTED)
    rejected(post("big.jpg", b"x" * (LIMIT + 1), "image/jpeg"), 413, "too_large", "ファイルは 10MB 以下にしてください")
    return f"{LIMIT:,} バイト→415（中身がテキスト）・{LIMIT + 1:,} バイト→413"


@check("V6 画素数は 4000万ちょうどまで受け付け、超えると 413（Pillow の既定では通る 4800万も止める）")
def _():
    ok = image_bytes("PNG", (8000, 5000), "L")
    accepted(post("a.png", ok, "image/png"), ok, "image", "png")
    for size in [(8000, 6000), (10000, 9000)]:
        rejected(post("b.png", image_bytes("PNG", size, "L"), "image/png"), 413, "too_large", "画像の画素数が大きすぎます（4000万画素まで）")
    return "8000×5000→受付・8000×6000→413・10000×9000→413"


@check("V7 PDF は 200 ページまで受け付け、201 ページは 413")
def _():
    ok = pdf_bytes(MAX_PDF_PAGES)
    accepted(post("book.pdf", ok, "application/pdf"), ok, "pdf", "pdf")
    rejected(post("book.pdf", pdf_bytes(MAX_PDF_PAGES + 1), "application/pdf"), 413, "too_large", "PDF は 200 ページ以下にしてください")
    return "200 ページ→受付・201 ページ→413"


@check("V8 利用者のファイル名はパスに使わず、up_＋ULID で採番した名前で保存する")
def _():
    png = image_bytes("PNG")
    before = set(Path.cwd().rglob("evil*"))
    for name in ["../../evil.png", "/tmp/evil.png"]:
        uid = accepted(post(name, png, "image/png"), png, "image", "png")
    eq(set(Path.cwd().rglob("evil*")), before, "evil という名前のファイルが増えていない")
    eq(Path("/tmp/evil.png").exists(), False, "/tmp/evil.png が作られていない")
    return f"../../evil.png と /tmp/evil.png → up_＋ULID（{len(uid)} 文字）.png"


@check("V9 file の項目が無いと 422 invalid_request（エラー本文は①と同じ形）")
def _():
    r = post("fridge.jpg", image_bytes("JPEG"), "image/jpeg", field="image")
    rejected(r, 422, "invalid_request", "入力値が正しくありません：file")
    return r.json()["error"]["message"]


finish("session02")
