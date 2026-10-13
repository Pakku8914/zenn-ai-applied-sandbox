"""セッション5：練習問題の解答コードの動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session05
"""

from __future__ import annotations

import asyncio

from anthropic import Anthropic

from kondate.llm import ChatResult, FakeProvider, Usage
from kondate.media import media_path
from kondate.verifykit import check, eq, finish
from src.session05.compare import scanned_pdf
from src.session05.documents import extract_pages
from src.session05.solutions import q1_blocks, q2_pages, q3_check, q4_dedupe, q5_feedback, q6_citations_api, q7_numbers

client = Anthropic()
BOOK = media_path("recipe_book.pdf").read_bytes()
PAGES = extract_pages(BOOK)


@check("S1 問題1：3通りの document ブロックの見積もりが count_tokens と一致し、不正な指定は例外にする")
def _():
    blocks = q1_blocks.blocks()
    expected = {"base64": 4807, "text": 29, "file": 1607}
    eq({k: q1_blocks.estimate(b) for k, b in blocks.items()}, expected, "見積もり")
    eq({k: q1_blocks.count(client, b) for k, b in blocks.items()}, expected, "count_tokens")
    png = media_path("receipt.png").read_bytes()
    for args in (("svg", "x"), ("base64", png), ("text", ""), ("file", "abc")):
        try:
            q1_blocks.make_document_block(*args)
        except ValueError:
            continue
        raise AssertionError(f"例外にならなかった: {args[0]}")
    return "base64=4807・text=29・file=1607／不正な指定 4 通りは ValueError"


@check("S2 問題2：recipe_book.pdf は全ページ文字あり→text、画像だけの PDF と表を読ませたい質問は pdf")
def _():
    eq(q2_pages.page_report(BOOK), [(1, True), (2, True), (3, True)], "recipe_book.pdf")
    scan = scanned_pdf()
    eq(q2_pages.page_report(scan), [(1, False)], "画像だけの PDF")
    eq((q2_pages.suggest(BOOK), q2_pages.suggest(scan), q2_pages.suggest(BOOK, needs_layout=True)), ("text", "pdf", "pdf"), "候補")
    return "text・pdf・pdf"


@check("S3 問題3：空白の違いは吸収し、短すぎる・範囲外・別ページの引用は通さない")
def _():
    eq(q3_check.results(), ["ok", "ok", "too_short", "page_out_of_range", "not_found", "ok"], "照合の結果")
    return "ok・ok・too_short・page_out_of_range・not_found・ok"


@check("S4 問題4：同じ利用者の同じ内容は同じ文書、別の利用者・別の内容は別の文書")
def _():
    rows = asyncio.run(q4_dedupe.run_cases())
    eq([(r[2], r[3], r[4]) for r in rows], [(201, "A", 3), (200, "A", 3), (201, "B", 3), (201, "C", 1)], "（status, 文書, ページ数）")
    return "201 A・200 A・201 B・201 C"


@check("S5 問題5：ページ違いを診断して聞き直し、2回目で確かめられる。2回とも駄目なら None")
async def _():
    llm = q5_feedback.demo_provider()
    answer, log = await q5_feedback.ask_with_feedback(llm, BOOK, PAGES, "肉じゃがは何人分ですか？")
    eq((answer.answer if answer else None, log), ("肉じゃがは4人分です。", [(1, 2, "wrong_page", 1), (2, 1, "ok", 1)]), "答えと診断")
    second = llm.requests[1].messages
    eq([m["role"] for m in second], ["user", "assistant", "user"], "再試行のメッセージ")
    assert "（1ページにあります）" in second[-1]["content"], second[-1]["content"]
    bad = FakeProvider([ChatResult(q5_feedback.answer_json(3), [], "end_turn", Usage(4888, 38))] * 2)
    answer, log = await q5_feedback.ask_with_feedback(bad, BOOK, PAGES, "肉じゃがは何人分ですか？")
    eq((answer, [r[2] for r in log]), (None, ["wrong_page", "wrong_page"]), "2回とも3ページ")
    return "wrong_page（実際は1ページ）→ ok／2回とも駄目なら None"


@check("S6 問題6：citations 機能の応答の形を {page, quote} に変換し、1ページ目で確かめられる")
def _():
    own = q6_citations_api.to_own_format(q6_citations_api.SAMPLE_CONTENT)
    eq(own["answer"], "レシピ集によると、肉じゃがは4人分です。", "answer")
    eq([(c["page"], c["quote"]) for c in own["citations"]], [(1, "R029　調理時間 35分　4人分　1人分 250kcal")], "citations")
    eq(q6_citations_api.verify(own, PAGES), ["ok"], "照合")
    return "1ページ → ok"


@check("S7 問題7：答えの数が引用で裏付けられないもの（2人分・5人分）だけを落とす")
def _():
    eq(q7_numbers.verdicts(), ["裏付けあり", "裏付けなし（2）", "裏付けあり", "裏付けあり", "裏付けなし（5）", "裏付けあり"], "判定")
    return "4人分・35分・全角の４・「1ページ」はあり／2人分・5人分はなし"


client.close()
finish("session05-solutions")
