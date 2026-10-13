"""セッション3：練習問題の解答コードの動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session03
"""

from __future__ import annotations

from anthropic import Anthropic

from kondate.media import media_path
from kondate.verifykit import check, eq, finish
from src.session03.count import count_input_tokens
from src.session03.images import prepare_image
from src.session03.make_variants import make_all
from src.session03.solutions import q1_sources, q2_estimate, q3_exif, q4_orientation, q5_tradeoff, q6_file_registry

client = Anthropic()
FRIDGE = media_path("fridge.jpg").read_bytes()
_paths = make_all()


@check("S1 問題1：3種類の image ブロックを作り分け、不正な指定は例外にする")
def _():
    blocks = {
        "base64": q1_sources.make_image_block("base64", FRIDGE, "image/jpeg"),
        "url": q1_sources.make_image_block("url", "https://example.com/fridge.jpg"),
        "file": q1_sources.make_image_block("file", "file_demo_fridge_0001"),
    }
    eq({k: q1_sources.count(client, b) for k, b in blocks.items()}, {"base64": 1617, "url": 1607, "file": 1607}, "input_tokens")
    for args in (("svg", "x"), ("url", "http://example.com/a.jpg"), ("base64", FRIDGE, "image/heic"), ("file", "abc")):
        try:
            q1_sources.make_image_block(*args)
        except ValueError:
            continue
        raise AssertionError(f"例外にならなかった: {args[:2]}")
    return "base64=1617・url=1607・file=1607／不正な指定 4 通りは ValueError"


@check("S2 問題2：8つの寸法の見積もりが count_tokens−7 と一致する")
def _():
    expected = [16, 726, 1610, 1610, 2352, 3888, 4784, 552]
    eq([q2_estimate.estimate(*s) for s in q2_estimate.SIZES], expected, "見積もり")
    eq([q2_estimate.counted(client, *s) for s in q2_estimate.SIZES], expected, "count_tokens−7")
    return "、".join(map(str, expected))


@check("S3 問題3：元の写真には EXIF と位置情報があり、前処理後には何も残らない")
def _():
    portrait = _paths["portrait"].read_bytes()
    eq(q3_exif.exif_report(FRIDGE), {"format": "JPEG", "size": (1280, 960), "has_exif": True, "has_gps": True,
                                     "orientation": None, "make": "KondateCam"}, "fridge.jpg")
    eq(q3_exif.exif_report(portrait)["orientation"], 6, "縦向き版の Orientation")
    for raw in (FRIDGE, portrait):
        r = q3_exif.exif_report(prepare_image(raw).data)
        eq((r["has_exif"], r["has_gps"], r["orientation"], r["make"]), (False, False, None, None), "前処理後")
    return "fridge.jpg：EXIF・GPS あり → 前処理後：なし"


@check("S4 問題4：Orientation 1〜8 のどれでも、前処理後は 1280×960 の正しい向きになる")
def _():
    rows = q4_orientation.check_all()
    eq([r["stored"] for r in rows], [(1280, 960)] * 4 + [(960, 1280)] * 4, "保存された寸法")
    eq([r["sent"] for r in rows], [(1280, 960)] * 8, "送る寸法")
    eq([r["ok"] for r in rows], [True] * 8, "元の向きと一致")
    return "1〜4 は 1280×960、5〜8 は 960×1280 で保存 → すべて 1280×960 に戻る"


@check("S5 問題5：長辺を縮めるほどトークンとバイト数は減り、文字は小さく、復元誤差は大きくなる")
def _():
    rows = q5_tradeoff.tradeoff(_paths["large"].read_bytes())
    eq([r["tokens"] for r in rows], [4784, 2352, 1036, 588, 266, 70], "画像トークン")
    eq([r["font_px"] for r in rows], [68, 42, 27, 20, 14, 7], "名札の文字の大きさ")
    eq([r["readable"] for r in rows], ["◯", "◯", "◯", "◯", "△", "×"], "読みやすさの目安")
    sizes = [r["bytes"] for r in rows]
    assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == len(sizes), sizes
    errors = [r["error"] for r in rows[1:]]  # 1568 以下で比べる（2576 と 1568 はどちらも元の 1280 より大きい）
    assert errors == sorted(errors) and len(set(errors)) == len(errors), errors
    return "トークン 4784 → 70・文字 68px → 7px・バイト数は単調減少・復元誤差は単調増加"


@check("S6 問題6：同じ利用者の同じ画像は一度だけアップロードし、file 参照は 1607 トークンで数えられる")
def _():
    fridge = prepare_image(FRIDGE)
    portrait = prepare_image(_paths["portrait"].read_bytes())
    reg = q6_file_registry.FileRegistry(q6_file_registry.fake_uploader)
    seen = []
    for user_id, p in (("u001", fridge), ("u001", fridge), ("u002", fridge), ("u001", portrait)):
        block = reg.block_for(user_id, p.data, p.media_type)
        seen.append((reg.uploads, count_input_tokens(client, [block])))
    eq(seen, [(1, 1607), (1, 1607), (2, 1607), (3, 1607)], "（アップロード累計, input_tokens）")
    return "アップロード 1 → 1 → 2 → 3・input_tokens はすべて 1607"


client.close()
finish("session03-solutions")
