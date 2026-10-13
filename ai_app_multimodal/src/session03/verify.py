"""セッション3の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session03
"""

from __future__ import annotations

import io

from anthropic import Anthropic
from PIL import Image, ImageChops, ImageStat

from kondate.media import media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session03.count import FRAME_TOKENS, count_input_tokens
from src.session03.images import base64_block, estimate_image_tokens, file_block, prepare_image, url_block
from src.session03.make_variants import make_all

QUESTION = "この写真に写っている食材は何ですか？"  # 18文字×3バイト＝54バイト → 18トークン
DUMMY_FILE_ID = "file_demo_fridge_0001"           # mockllm は中身を取りに行かないので任意の文字列でよい

client = Anthropic()
FRIDGE = media_path("fridge.jpg").read_bytes()
_paths = make_all()
LARGE = _paths["large"].read_bytes()
PORTRAIT = _paths["portrait"].read_bytes()

# 寸法 → 画像トークン（mockllm の式で手計算した値）
SIZES = {
    (100, 100): 16, (600, 900): 726, (800, 600): 638, (1280, 960): 1610,
    (960, 1280): 1610, (1568, 1176): 2352, (4000, 3000): 4784,
}


def blank_png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def image_info(raw: bytes) -> tuple[tuple[int, int], int | None, bool]:
    """（保存された寸法, Orientation, 位置情報の有無）"""
    with Image.open(io.BytesIO(raw)) as img:
        exif = img.getexif()
        return img.size, exif.get(0x0112), len(exif.get_ifd(0x8825)) > 0


def mean_diff(a: bytes, b: bytes) -> float:
    """2枚の画像の平均的な明るさの差（0〜255）。向きが合っていれば JPEG の劣化分しか差が出ない。"""
    with Image.open(io.BytesIO(a)) as x, Image.open(io.BytesIO(b)) as y:
        gx = x.convert("L").resize((320, 240))
        gy = y.convert("L").resize((320, 240))
    return ImageStat.Stat(ImageChops.difference(gx, gy)).mean[0]


@check("V1 image ブロックの3つの source を count_tokens に送ると、base64 は寸法から、url・file は固定 1600 で数えられる")
def _():
    p = prepare_image(FRIDGE)
    got = {
        "base64": count_input_tokens(client, [base64_block(p.data, p.media_type)]),
        "url": count_input_tokens(client, [url_block("https://example.com/fridge.jpg")]),
        "file": count_input_tokens(client, [file_block(DUMMY_FILE_ID)]),
    }
    eq(got, {"base64": 1617, "url": 1607, "file": 1607}, "input_tokens")
    return "base64=1617・url=1607・file=1607（いずれも枠の 7 を含む）"


@check("V2 寸法からの見積もりが mockllm の count_tokens と一致する")
def _():
    eq({s: estimate_image_tokens(*s) for s in SIZES}, SIZES, "見積もり")
    counted = {s: count_input_tokens(client, [base64_block(blank_png(*s), "image/png")]) - FRAME_TOKENS for s in SIZES}
    eq(counted, SIZES, "count_tokens − 7")
    return "、".join(f"{w}×{h}={t}" for (w, h), t in SIZES.items())


@check("V3 演習用の画像：4000×3000 の拡大版と Orientation=6 の縦向き版を作り、どちらにも位置情報（GPS）が残っている")
def _():
    eq(image_info(FRIDGE), ((1280, 960), None, True), "fridge.jpg")
    eq(image_info(LARGE), ((4000, 3000), None, True), "拡大版")
    eq(image_info(PORTRAIT), ((960, 1280), 6, True), "縦向き版")
    return "拡大版 4000×3000・縦向き版 960×1280（Orientation=6）"


@check("V4 前処理で 4000×3000 は 1568×1176 に縮み、画像トークンが 4784 → 2352 になる")
def _():
    before = count_input_tokens(client, [base64_block(LARGE)]) - FRAME_TOKENS
    p = prepare_image(LARGE)
    eq(p.sent_size, (1568, 1176), "送る寸法")
    after = count_input_tokens(client, [base64_block(p.data, p.media_type)]) - FRAME_TOKENS
    eq((before, after, p.tokens), (4784, 2352, 2352), "画像トークン（前・後・見積もり）")
    assert len(p.data) < len(LARGE), (len(p.data), len(LARGE))
    small = prepare_image(FRIDGE)
    eq((small.sent_size, len(small.data)), ((1280, 960), 89080), "fridge.jpg は拡大せず、作り直した JPEG のバイト数")
    return "4000×3000 → 1568×1176・4784 → 2352／fridge.jpg は 1280×960 のまま 89080 バイト"


@check("V5 縦向き版は exif_transpose で寸法が入れ替わり、元の写真と同じ向きに戻る")
def _():
    p = prepare_image(PORTRAIT)
    eq((p.stored_size, p.original_size, p.sent_size), ((960, 1280), (1280, 960), (1280, 960)), "保存・向きを直したあと・送る寸法")
    diff = mean_diff(p.data, FRIDGE)
    assert diff < 8, f"元の写真との差が大きい（{diff:.2f}）＝向きが戻っていない"
    return "保存 960×1280 → 向きを直して 1280×960"


@check("V6 前処理後の JPEG には EXIF（位置情報を含む）が残らない")
def _():
    for name, raw in (("fridge.jpg", FRIDGE), ("拡大版", LARGE), ("縦向き版", PORTRAIT)):
        p = prepare_image(raw)
        eq(p.exif_removed, True, f"{name} の exif_removed")
        with Image.open(io.BytesIO(p.data)) as img:
            eq((len(img.getexif()), "exif" in img.info), (0, False), f"{name} の前処理後の EXIF")
    eq(prepare_image(blank_png(800, 600)).exif_removed, False, "EXIF の無い PNG")
    return "3枚とも EXIF 0 件／もともと EXIF の無い PNG は exif_removed=False"


@check("V7 file_id で参照した image ブロックは messages.create でも受理され、mockllm は寸法を「サイズ不明」として扱う")
def _():
    s = get_settings()

    def ask(block: dict):
        return client.messages.create(
            model=s.llm_model, max_tokens=s.llm_max_tokens,
            messages=[{"role": "user", "content": [block, {"type": "text", "text": QUESTION}]}],
        )

    by_file = ask(file_block(DUMMY_FILE_ID))
    p = prepare_image(FRIDGE)
    by_b64 = ask(base64_block(p.data, p.media_type))
    eq((by_file.usage.input_tokens, by_b64.usage.input_tokens), (1625, 1635), "input_tokens（file・base64）")
    assert by_file.content[0].text.startswith("写真（1枚・サイズ不明）から"), by_file.content[0].text
    assert by_b64.content[0].text.startswith("写真（1枚・1280×960）から"), by_b64.content[0].text
    return "file 参照 1625（サイズ不明）・base64 1635（1280×960）"


client.close()
finish("session03")
