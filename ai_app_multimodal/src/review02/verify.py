"""復習2（セッション2〜7の横断復習）の解答コードの動作確認。各解答の main() の出力が、解答章に載せた
「期待される出力」と一致するかを見る。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review02
"""

from __future__ import annotations

import contextlib
import io
import logging

from kondate.verifykit import check, eq, finish
from src.review02.solutions import (
    q1_windows, q2_tokens, q3_review, q4_match, q5_ask, q6_where, q7_after_failure,
)

logging.getLogger("src.review02").setLevel(logging.ERROR)
logging.getLogger("pypdf").setLevel(logging.ERROR)

EXPECTED = {
    "q1": """\
u001 receipt.png → uploads 201 image ／ documents 415 unsupported_media「PDF を送ってください」 ／ receipts 201 image・要確認 0 件・usage 778/104
u001 receipt.pdf → uploads 201 pdf ／ documents 201 1ページ ／ receipts 201 pdf・要確認 0 件・usage 1652/104
u001 receipt.png（2回目） → uploads 201 image ／ documents 415 unsupported_media「PDF を送ってください」 ／ receipts 409 duplicate「このレシートはすでに取り込み済みです」
u001 receipt.pdf（2回目） → uploads 201 pdf ／ documents 200 1ページ ／ receipts 409 duplicate「このレシートはすでに取り込み済みです」
u002 receipt.png → uploads 201 image ／ documents 415 unsupported_media「PDF を送ってください」 ／ receipts 201 image・要確認 0 件・usage 778/104
upload_id: 5 件・すべて別
document_id: 1 種類
mockllm のシナリオ: receipt×3
""",
    "q2": """\
receipt.png（前処理あり）＋取り込みの指示: 枠 7 + system 0 + 画像 726 + テキスト 45 = 778 ／ count_tokens 778 ／ 一致
receipt.pdf＋取り込みの指示: 枠 7 + system 0 + 文書 1600 + テキスト 45 = 1652 ／ count_tokens 1652 ／ 一致
recipe_book.pdf（3ページ）＋質問: 枠 7 + system 69 + 文書 4800 + テキスト 12 = 4888 ／ count_tokens 4888 ／ 一致
recipe_book_full.pdf の [29]＋質問: 枠 7 + system 69 + 文書 1600 + テキスト 12 = 1688 ／ count_tokens 1688 ／ 一致
recipe_book_full.pdf の [11, 29, 84]＋質問: 枠 7 + system 69 + 文書 4800 + テキスト 12 = 4888 ／ count_tokens 4888 ／ 一致
recipe_book_full.pdf（120ページ）全体＋質問: 枠 7 + system 69 + 文書 192000 + テキスト 12 = 192088 ／ count_tokens 192088 ／ 一致
""",
    "q3": """\
合計が合わない（画像） → needs_review=True・total_mismatch(全体)・試行 1 回
合計が合わない（PDF） → needs_review=True・total_mismatch(全体)、text_mismatch(全体)・試行 1 回
つじつまの合う読み違い（画像） → needs_review=False・なし・試行 1 回
つじつまの合う読み違い（PDF） → needs_review=True・text_mismatch(全体)、text_mismatch(1 キャベツ)・試行 1 回
牛乳が 0 円（画像） → needs_review=True・price_out_of_range(3 牛乳)・試行 1 回
未来の日付（PDF） → needs_review=True・invalid_date(全体)、text_mismatch(全体)・試行 1 回
冷蔵庫の食材（セッション4） → needs_review=True・unknown_name(1 鶏ムネ肉)、low_confidence(2 にんじん)
""",
    "q4": """\
送った [29] の 1 ページ目「調理時間 35分　4人分」 → 元の 29 ページ・ok
送った [29] の 1 ページ目「調理時間 ３５分 ４人分」 → 元の 29 ページ・ok
送った [29] の 1 ページ目「肉じゃがは4人分です」 → 元の 29 ページ・not_found
送った [29] の 1 ページ目「4人分」 → 元の 29 ページ・too_short
送った [29] の 2 ページ目「調理時間 35分　4人分」 → page_out_of_range（送っていないページ）
送った [11, 29, 84] の 1 ページ目「調理時間 35分　4人分」 → 元の 11 ページ・not_found
送った [11, 29, 84] の 2 ページ目「調理時間 35分　4人分」 → 元の 29 ページ・ok
品目「卵(10個入り)」248円 → 一致
品目「たまご」248円 → text_mismatch
品目「牛乳」282円 → text_mismatch
品目「キャベツ」1072円 → 一致
""",
    "q5": """\
120ページ・pages=[29] → 200 引用 29 ページ・usage 12/38・キャッシュ 作成 1676／読み出し 0・LLM 1 回
120ページ・pages なし → 200 引用 29 ページ・usage 12/38・キャッシュ 作成 0／読み出し 1676・LLM 1 回
120ページ・pages=[29, 29] → 200 引用 29 ページ・usage 12/38・キャッシュ 作成 0／読み出し 1676・LLM 1 回
120ページ・pages=[84, 29, 11] → 502 invalid_output「回答の根拠を文書の中で確かめられませんでした」・usage 24/76・キャッシュ 作成 4876／読み出し 4876・LLM 2 回
120ページ・pages なし・「おすすめはどれですか？」 → 422 invalid_request「読むページを決められませんでした。pages でページ番号を指定してください」・usage 0/0・キャッシュ 作成 0／読み出し 0・LLM 0 回
120ページ・pages=1〜21 → 422 invalid_request「pages は 1〜20 個で指定してください」・usage 0/0・キャッシュ 作成 0／読み出し 0・LLM 0 回
3ページ・pages なし → 200 引用 1 ページ・usage 12/38・キャッシュ 作成 4876／読み出し 0・LLM 1 回
3ページ・キャッシュの印なし（セッション5の作り） → 200 引用 1 ページ・usage 4888/38・キャッシュ 作成 0／読み出し 0・LLM 1 回
mockllm のシナリオ: recipe_pdf_ask×7
""",
    "q6": """\
recipe_book_full.pdf（120ページ） → uploads 201 pdf ／ documents 201 120ページ ／ import 14 回に分けて 120 件・重複除去 13・取りこぼし 0 ページ・入力 212800・LLM 14 回
白紙の PDF（200ページ） → uploads 201 pdf ／ documents 201 200ページ ／ import 23 回に分けて 0 件・重複除去 0・取りこぼし 200 ページ・入力 355200・LLM 23 回
白紙の PDF（201ページ） → uploads 413 too_large ／ documents 413 too_large「PDF は 200 ページ以下にしてください」 ／ import なし・LLM 0 回
中身は文章（名前は book.pdf） → uploads 415 unsupported_media ／ documents 415 unsupported_media「PDF を送ってください」 ／ import なし・LLM 0 回
先頭だけ %PDF- の壊れたファイル → uploads 415 unsupported_media ／ documents 415 unsupported_media「PDF を送ってください」 ／ import なし・LLM 0 回
receipt.png → uploads 201 image ／ documents 415 unsupported_media「PDF を送ってください」 ／ import なし・LLM 0 回
10MiB を1バイト超える PDF → uploads 413 too_large ／ documents 413 too_large「ファイルは 10MB 以下にしてください」 ／ import なし・LLM 0 回
""",
    "q7": """\
receipt.png・壊れた JSON が2回 → 502 invalid_output「読み取り結果の形式が正しくありませんでした」・usage 1556/208・LLM 2 回
receipt.png・再送（mockllm） → 201 image・usage 778/104・LLM 1 回
receipt.png・もう一度 → 409 duplicate「このレシートはすでに取り込み済みです」・usage 0/0・LLM 0 回
receipt.pdf・上流が 529 → 503 upstream_unavailable「レシートの読み取りに失敗しました。時間をおいて試してください」・usage 0/0・LLM 1 回
receipt.pdf・再送（mockllm） → 201 pdf・usage 1652/104・LLM 1 回
120ページの取り込み・running 3/14 で取り消す → cancelled 3/14 → progress だけで終わる・result None・LLM 4 回
同じ文書をもう一度取り込む → succeeded 14/14 → done・120 件・LLM 14 回
3ページの取り込み・上流が 529 → failed 0/1 → error「文書の読み取りに失敗しました。時間をおいて試してください」・LLM 1 回
mockllm が返した状態コード: 200×2・529×2
""",
}

SOLUTIONS = {"q1": q1_windows, "q2": q2_tokens, "q3": q3_review, "q4": q4_match, "q5": q5_ask, "q6": q6_where,
             "q7": q7_after_failure}
TITLES = {
    "q1": "問題1 同じレシートを3つの窓口に送る（201・200・409 の違い）",
    "q2": "問題2 画像・PDF・ページ選択した PDF の入力トークンを式で組み立てる",
    "q3": "問題3 レシートの読み違いを要確認に回し、食材の要確認と同じ形で要約する",
    "q4": "問題4 引用の検証とレシートの文字の突き合わせを、同じ正規化で比べる",
    "q5": "問題5 120ページの文書への質問：ページ選択・キャッシュ・再試行と usage",
    "q6": "問題6 大きな PDF・偽装した PDF がどこで止まるか",
    "q7": "問題7 失敗したあとに何が残るか（再送・取り消し・上流の失敗）",
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


finish("review02")
