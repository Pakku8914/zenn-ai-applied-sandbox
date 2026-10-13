"""recipe_book.pdf を「PDF のまま」「file_id で参照」「抜き出した文字」で送ったときの入力トークンを比べる。
画像だけの PDF（スキャンした紙の代わり）からは、pypdf では文字が抜けないことも確かめる。

    docker compose exec api python -m src.session05.compare
"""

from __future__ import annotations

import io

from anthropic import Anthropic
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from kondate.media import media_path
from kondate.settings import get_settings
from src.session05.documents import extract_pages, file_block, normalize, pdf_block, text_block

FONT = "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf"
FRAME_TOKENS = 4 + 3  # mockllm の式で、リクエスト1件（4）とメッセージ1件（3）の枠の分
DUMMY_FILE_ID = "file_demo_recipe_book_0001"  # mockllm は中身を取りに行かないので任意の文字列でよい


def count_input_tokens(client: Anthropic, content: list[dict]) -> int:
    """content を user メッセージ1件として送ったときの input_tokens を返す（課金なし）。"""
    res = client.messages.count_tokens(model=get_settings().llm_model, messages=[{"role": "user", "content": content}])
    return res.input_tokens


def scanned_pdf() -> bytes:
    """文字を「絵」として描いた1ページの PDF。スキャンした紙と同じく、中に文字のデータは無い。"""
    img = Image.new("RGB", (1240, 1754), "white")  # A4 を 150dpi で
    d = ImageDraw.Draw(img)
    d.text((120, 160), "肉じゃが", font=ImageFont.truetype(FONT, 72), fill="black")
    d.text((120, 300), "R029　調理時間 35分　4人分", font=ImageFont.truetype(FONT, 40), fill="black")
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def main() -> None:
    book = media_path("recipe_book.pdf").read_bytes()
    text = "\n".join(extract_pages(book))
    scan = scanned_pdf()
    client = Anthropic()
    try:
        print(f"PDF のまま（base64）：input_tokens={count_input_tokens(client, [pdf_block(book)])}")
        print(f"file_id で参照：input_tokens={count_input_tokens(client, [file_block(DUMMY_FILE_ID)])}")
        n = count_input_tokens(client, [text_block(text)])
        print(f"抜き出した文字（text）：input_tokens={n}（{len(text.encode('utf-8'))} バイト）")
        pages = len(PdfReader(io.BytesIO(scan)).pages)
        chars = len(normalize("".join(extract_pages(scan))))
        n_scan = count_input_tokens(client, [pdf_block(scan)])
        print(f"画像だけの PDF：{pages} ページ・抜き出せた文字 {chars} 字・PDF のまま送ると input_tokens={n_scan}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
