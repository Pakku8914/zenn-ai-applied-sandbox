"""復習1（セッション2〜4の横断復習）の解答コードの動作確認。各解答の main() の出力が、解答章に載せた
「期待される出力」と一致するかを見る。api コンテナの中で実行する：

    docker compose exec api python src/review01/verify.py
"""

from __future__ import annotations

import contextlib
import io
import logging

from kondate.verifykit import check, eq, finish
from src.review01.solutions import q1_route, q2_dimensions, q3_breakdown, q4_retry_usage, q5_response, q6_pipeline

logging.getLogger("src.review01").setLevel(logging.ERROR)

EXPECTED = {
    "q1": """\
fridge.jpg → 受付 image・拡張子 jpg → 送信 1280×960・1610 トークン
fridge.png（中身は JPEG） → 受付 image・拡張子 jpg → 送信 1280×960・1610 トークン
memo.png（中身は文章） → 415 unsupported_media「JPEG・PNG・WebP・GIF の画像か PDF を送ってください」
broken.png（先頭だけ PNG） → 415 unsupported_media「JPEG・PNG・WebP・GIF の画像か PDF を送ってください」
receipt.png → 受付 image・拡張子 png → 送信 600×900・726 トークン
recipe_book.pdf → 受付 pdf・拡張子 pdf → 画像ではないので前処理しない
""",
    "q2": """\
8000×6000 の PNG → 413 too_large「画像の画素数が大きすぎます（4000万画素まで）」
縦向きの写真 → 保存 960×1280・向きを直して 1280×960・送信 1280×960・EXIF を除去・1610 トークン（前処理なし 1610）
4000×3000 の写真 → 保存 4000×3000・向きを直して 4000×3000・送信 1568×1176・EXIF を除去・2352 トークン（前処理なし 4784）
fridge.jpg → 保存 1280×960・向きを直して 1280×960・送信 1280×960・EXIF を除去・1610 トークン（前処理なし 1610）
""",
    "q3": """\
fridge.jpg（前処理あり）: 枠 7 + 画像 1610 + 指示文 51 = 1668 ／ count_tokens 1668 ／ 一致
4000×3000（前処理あり）: 枠 7 + 画像 2352 + 指示文 51 = 2410 ／ count_tokens 2410 ／ 一致
4000×3000（前処理なし）: 枠 7 + 画像 4784 + 指示文 51 = 4842 ／ count_tokens 4842 ／ 一致
""",
    "q4": """\
fridge.jpg（前処理あり）・正常: 200・試行 1 回・usage 1668/194
fridge.jpg（前処理あり）・範囲外→正常: 200・試行 2 回・usage 3336/388
fridge.jpg（前処理あり）・範囲外が2回: 502 invalid_output・試行 2 回・usage 3336/388
fridge.jpg（前処理あり）・max_tokens で切れた: 502 invalid_output・試行 1 回・usage 1668/100
4000×3000（前処理あり）・範囲外→正常: 200・試行 2 回・usage 4820/388
4000×3000（前処理なし）・範囲外→正常: 200・試行 2 回・usage 9684/388
""",
    "q5": """\
応答の項目: ingredients, needs_review, issues, image, usage
ingredients: キャベツ、鶏ムネ肉、にんじん、卵、キャベツ（5 件）
needs_review: True
issues: 1 鶏ムネ肉 unknown_name ／ 2 にんじん low_confidence
image: sent_size=[1280, 960]・exif_removed=True・bytes=89080
usage: input_tokens=1668・output_tokens=194
確認済みの食材: キャベツ、卵
search_recipes: R119, R039, R038, R064, R067
""",
    "q6": """\
fridge.jpg → 200 食材 5 件・要確認 0 件・usage 1668/194・LLM 1 回
縦向きの写真 → 200 食材 5 件・要確認 0 件・usage 1668/194・LLM 1 回
4000×3000 の写真 → 200 食材 5 件・要確認 0 件・usage 2410/194・LLM 1 回
recipe_book.pdf → 415 unsupported_media「JPEG・PNG・WebP・GIF の画像を送ってください」・usage 0/0・LLM 0 回
8000×6000 の PNG → 413 too_large「画像の画素数が大きすぎます（4000万画素まで）」・usage 0/0・LLM 0 回
10MiB を1バイト超えるファイル → 413 too_large「画像は 10MB 以下にしてください」・usage 0/0・LLM 0 回
範囲外の confidence が2回続く → 502 invalid_output「読み取り結果の形式が正しくありませんでした」・usage 3336/388・LLM 2 回
上流が 529 を返す → 503 upstream_unavailable「画像の読み取りに失敗しました。時間をおいて試してください」・usage 0/0・LLM 1 回
mockllm が返した状態コード: 200×3・529×1
""",
}

SOLUTIONS = {"q1": q1_route, "q2": q2_dimensions, "q3": q3_breakdown, "q4": q4_retry_usage, "q5": q5_response, "q6": q6_pipeline}
TITLES = {
    "q1": "問題1 中身で受付を判定し、通った画像だけを前処理して見積もる",
    "q2": "問題2 画素数・向き・大きさの違う写真で、受付と前処理の役割を見分ける",
    "q3": "問題3 入力トークンの内訳を式で組み立て、count_tokens と一致させる",
    "q4": "問題4 前処理の有無と再試行で usage の合計がどう変わるか",
    "q5": "問題5 応答を API契約どおりに組み立て、確認済みの食材だけで検索する",
    "q6": "問題6 受付から要確認までを1本につなぎ、8種類の入力を流す",
}


def run(key: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        SOLUTIONS[key].main()
    return buf.getvalue()


for n, key in enumerate(SOLUTIONS, start=1):
    @check(f"V{n} {TITLES[key]}")
    def _(key: str = key) -> str:
        eq(run(key), EXPECTED[key], f"{key} の出力")
        return f"{len(EXPECTED[key].splitlines())} 行が一致"


finish("review01")
