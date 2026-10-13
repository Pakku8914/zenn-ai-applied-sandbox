"""セッション6：練習問題の解答コードの動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session06
"""

from __future__ import annotations

import asyncio

import httpx2

from kondate.media import media_path
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish
from src.session06.solutions import q1_limits, q2_pick, q3_select, q4_merge, q5_cache, q6_registry, q7_parallel

FULL = media_path("recipe_book_full.pdf").read_bytes()


@check("S1 問題1：上限の判定と見積もり（base64 で約 4/3 倍・予算 50,000 なら 31 ページ）")
def _():
    got = [q1_limits.assess(p, b) for p, b in q1_limits.CASES]
    eq(got, [[], [], ["app_pages"], ["app_pages", "api_pages"], ["app_bytes", "api_request"]], "判定")
    eq((q1_limits.base64_size(25_000_000), q1_limits.pages_within(50_000)), (33_333_336, 31), "base64 と予算")
    return "送れる・送れる・app_pages・app_pages+api_pages・app_bytes+api_request／31ページ"


@check("S2 問題2：キーワードと表記ゆれから当たりを付け、20ページを超えたら ValueError")
def _():
    index = q2_pick.load_index()
    got = [q2_pick.pick_pages(index, k) for k in q2_pick.CASES]
    eq(got, [[11, 12], [13, 14, 27, 28], [84, 85, 86, 87], [5, 6, 7, 31, 84, 85, 86, 87], [113, 114, 115]], "当たり")
    try:
        q2_pick.pick_pages(index, ["肉"])
    except ValueError:
        pass
    else:
        raise AssertionError("「肉」が ValueError になりませんでした")
    return "生姜焼き→[11, 12]・みそ→味噌も含めて8ページ・肉→ValueError"


@check("S3 問題3：[84, 29, 29, 11] は昇順・重複なしの3ページ、2ページ目は元の29ページ")
def _():
    sel = q3_select.select(FULL, [84, 29, 29, 11])
    eq((sel.sent, q3_select.to_original(sel, 2)), ([11, 29, 84], 29), "送るページと番号の戻し")
    for bad in ([], [0], [121]):
        try:
            q3_select.select(FULL, bad)
        except ValueError:
            continue
        raise AssertionError(f"ValueError になりませんでした: {bad}")
    return "[11, 29, 84]・2→29・[]/[0]/[121]→ValueError"


@check("S4 問題4：範囲の数と統合（重複1・食い違い R005・取りこぼし6ページ）")
def _():
    eq([len(q4_merge.chunk_ranges(*a)) for a in ((120, 10, 1), (120, 10, 0), (25, 10, 2))], [14, 12, 3], "範囲の数")
    eq(q4_merge.chunk_ranges(7, 3, 1), [(1, 3), (3, 5), (5, 7)], "7ページ")
    eq(q4_merge.merge(q4_merge.CHUNKS, 7), {"ids": ["R001", "R002", "R003", "R004", "R005", "R007"], "duplicates_removed": 1,
                                             "conflicts": ["R005"], "missing_pages": [6]}, "統合")
    return "14・12・3 個／6件・重複除去 1・食い違い ['R005']・取りこぼし [6]"


@check("S5 問題5：文書の後ろに置くと質問が変わっても読み出し、質問の後ろに置くと同じ質問のときだけ読み出し")
def _():
    with httpx2.Client(base_url=get_settings().mockllm_url, timeout=5.0) as c:
        c.post("/_mock/reset").raise_for_status()
    doc, q = q5_cache.run("document"), q5_cache.run("question")
    eq(doc, [(12, 1676, 0), (16, 0, 1676), (12, 0, 1676)], "文書の後ろ")
    eq(q, [(0, 1688, 0), (0, 1692, 0), (0, 0, 1688)], "質問の後ろ")
    eq((q5_cache.weighted(doc), q5_cache.weighted(q)), (2470.2, 4393.8), "換算")
    return "文書の後ろ 2470.2・質問の後ろ 4393.8（キャッシュなし 5068）"


@check("S6 問題6：実行中は同じジョブ、別の利用者・取り消したあとは新しいジョブ")
def _():
    eq(asyncio.run(q6_registry.demo()), [
        "1回目: 新しく作った",
        "2回目（実行中）: 同じジョブ・running 3/14（21%）・ID が同じ: True",
        "別の利用者: 新しく作った",
        "取り消したあと: cancelled 3/14（21%）",
        "もう一度: 新しく作った",
    ], "表示")
    return "同じジョブ（running 3/14（21%））→ 取り消し → 新しく作った"


@check("S7 問題7：同時に3つまで読み、終わる順番がばらばらでも逐次版と同じ結果")
def _():
    eq(asyncio.run(q7_parallel.demo()), [
        "同時に読んだ範囲の最大数: 3",
        "逐次版と同じ結果: True（120件・食い違い ['R010']）",
        "進捗の通知: 14 回・最後は 14/14・単調に増える: True",
        "入力トークン: 212,800",
    ], "表示")
    return "最大3・逐次版と同じ・進捗 14 回"


finish("session06-solutions")
