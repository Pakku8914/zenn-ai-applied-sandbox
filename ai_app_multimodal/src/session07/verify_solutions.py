"""セッション7：練習問題の解答コードの動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session07
"""

from __future__ import annotations

import asyncio

from anthropic import Anthropic

from kondate.media import media_path
from kondate.verifykit import check, eq, finish
from src.session07.solutions import q1_blocks, q2_checks, q3_text, q4_inflight, q5_confirm, q6_possible_dup


@check("S1 問題1：画像は image・PDF は document。見積もりは count_tokens と一致（778・1652）")
def _():
    with Anthropic() as client:
        got = [q1_blocks.summary(media_path(n).read_bytes(), client) for n in ("receipt.png", "receipt.pdf")]
    eq(got, [("image", "image/jpeg", 778, 778), ("document", "application/pdf", 1652, 1652)], "（種類, media_type, 見積もり, count_tokens）")
    return "receipt.png 778・receipt.pdf 1652"


@check("S2 問題2：6通りの読み取り結果に付く印")
def _():
    eq(q2_checks.results(), [
        ("A そのまま", []),
        ("B 合計の桁を入れ替えた", [("total_mismatch", None)]),
        ("C 区切りの無い日付", [("invalid_date", None)]),
        ("D 時刻つきの日付", [("invalid_date", None)]),
        ("E 値引きの行", [("price_out_of_range", 4)]),
        ("F 未来の日付と桁違いの合計", [("invalid_date", None), ("total_mismatch", None)]),
    ], "検査の結果")
    return "A なし・B total_mismatch・C/D invalid_date・E price_out_of_range（4）・F invalid_date＋total_mismatch"


@check("S3 問題3：年月日・スラッシュ・円で終わる金額・全角も読める")
def _():
    eq(q3_text.results(), {
        "receipt.pdf": (("2026-10-01", 1072, [198, 228, 248, 398, 1072]), ("2026-10-01", 1072, [198, 228, 248, 398, 1072])),
        "全角と年月日": ((None, 398, [398]), ("2026-10-01", 398, [398])),
        "円で終わる金額": ((None, None, []), ("2026-10-01", 426, [198, 228, 426])),
        "文字なし": (None, None),
    }, "（本文の版, 広げた版）")
    return "receipt.pdf は同じ・全角と年月日／円で終わる金額は広げた版だけが読める"


@check("S4 問題4：同時に2回 → 201・409 で LLM は1回、失敗のあとの再送は 201")
def _():
    eq(asyncio.run(q4_inflight.run_cases()), {"concurrent": ([201, 409], 1), "after_failure": [502, 201]}, "結果")
    return "同時→[201, 409]・呼び出し1回／失敗→再送 [502, 201]"


@check("S5 問題5：直した値を検査し直して確認済みにする")
def _():
    eq(asyncio.run(q5_confirm.run_cases()), [
        ("A 取り込み", ["text_mismatch", "text_mismatch"]),
        ("A キャベツを198円・合計1072円に直す", (200, "confirmed", [], [])),
        ("B 取り込み", ["total_mismatch"]),
        ("B 直さずに確定", (200, "needs_review", ["total_mismatch"], None)),
        ("B 合計の不一致を承知で確定", (200, "confirmed", [], ["total_mismatch"])),
        ("B 日付の問題を承知にしようとする", (422, "invalid_request")),
        ("B 別の利用者", (404, "not_found")),
    ], "結果")
    return "直す→confirmed・直さない→needs_review・承知→confirmed・invalid_date は承知できない（422）・他人→404"


@check("S6 問題6：SHA256 が違っても、店名・購入日・合計が同じなら possible_duplicate")
def _():
    eq(q6_possible_dup.run_cases(), [
        ("同じレシートの PDF", ["possible_duplicate"]),
        ("店名に空白が入った", ["possible_duplicate"]),
        ("別の日", []),
        ("別の利用者", []),
    ], "結果")
    return "PDF→印あり・空白の違い→印あり・別の日→なし・別の利用者→なし"


finish("session07 solutions")
