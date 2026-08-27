#!/usr/bin/env python3
"""セッション6で使うシナリオ（ScriptedClient に渡す固定の応答列）。

`scenarios/*.json` に置いてもよいが、章の中だけで使う短いものはコードの近くに
置いたほうが読みやすい（セッション3と同じ方針）。

`write_file` の content にある `__REPORT__` は「本文は状態から組み立てて差し替える」
ための目印である。レポート本文をモデルの出力に依存させないための工夫。
"""

from __future__ import annotations

# 本文の主役。9手で完走する（途中で会議室の競合が1回起きる）
RESEARCH = {
    "name": "state_research",
    "turns": [
        # 0: planning ― 計画を立てるだけ。ツールは呼ばない
        {"thought": "サブゴールは3つ。①経費精算の規程を読む ②申請を集める ③レポートにする。"},
        # 1: collecting ― まず規程。次の予定を思考に書いているのがあとで問題になる
        {"thought": "まず規程を読む。このあと list_expenses で申請を集め、write_file で保存する。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        # 2: collecting ― 独立した読み取り2件を1ステップでまとめて頼む（並列にできる）
        {"thought": "申請一覧と関連文書は互いに独立なので同時に取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}},
                   {"name": "search_docs", "args": {"query": "経費 規程", "limit": 2}}]},
        # 3: checking ― 突き合わせるだけ。ツールは呼ばない
        {"thought": "基準額以上なのに submitted のままの申請を洗い出す。"},
        # 4: drafting ― 本文は __REPORT__ の目印で状態から差し替える
        {"thought": "調査結果をレポートに保存する。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session06/report.md", "content": "__REPORT__"}}]},
        # 5: booking ― 報告会の会議室。10:00 は必ず競合する枠
        {"thought": "報告会のためにみなとを押さえる。",
         "calls": [{"name": "book_room", "args": {"room": "みなと", "minutes": 60}}]},
        # 6: rescheduling ― 次の枠を選ぶだけ。ツールは呼ばない
        {"thought": "その枠は埋まっていた。次の候補に移る。"},
        # 7: booking ― 状態が選んだ枠で取り直す
        {"thought": "次の枠で予約し直す。",
         "calls": [{"name": "book_room", "args": {"room": "みなと", "minutes": 60}}]},
        # 8: done ― 最終回答
        {"thought": "すべて終わった。結果を報告する。",
         "final": "規程違反の疑いがある申請 2 件（EXP-0002 / EXP-0004）をレポートに整理し、"
                  "報告会の会議室（みなと 11:00）を予約しました。"},
    ],
}

# checking と rescheduling をモデルに聞かない設計にしたときの応答列（7手）
RESEARCH_AUTO = {
    "name": "state_research_auto",
    "turns": [
        {"thought": "サブゴールは3つ。①経費精算の規程を読む ②申請を集める ③レポートにする。"},
        {"thought": "まず規程を読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "申請一覧と関連文書は互いに独立なので同時に取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}},
                   {"name": "search_docs", "args": {"query": "経費 規程", "limit": 2}}]},
        {"thought": "調査結果をレポートに保存する。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session06/report.md", "content": "__REPORT__"}}]},
        {"thought": "報告会のためにみなとを押さえる。",
         "calls": [{"name": "book_room", "args": {"room": "みなと", "minutes": 60}}]},
        {"thought": "次の枠で予約し直す。",
         "calls": [{"name": "book_room", "args": {"room": "みなと", "minutes": 60}}]},
        {"thought": "すべて終わった。結果を報告する。",
         "final": "規程違反の疑いがある申請 2 件（EXP-0002 / EXP-0004）をレポートに整理し、"
                  "報告会の会議室（みなと 11:00）を予約しました。"},
    ],
}

# 違反が0件だったときの道（checking から別の枝へ抜ける）。6手
CLEAN = {
    "name": "state_clean",
    "turns": [
        {"thought": "サブゴールは3つ。まず規程から。"},
        {"thought": "規程を読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "申請一覧と関連文書をまとめて取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}},
                   {"name": "search_docs", "args": {"query": "経費 規程", "limit": 2}}]},
        {"thought": "基準額以上なのに submitted のままの申請を洗い出す。"},
        {"thought": "該当なしと分かったので、そのまま報告文を残す。",
         "calls": [{"name": "write_file",
                    "args": {"path": "session06/report_clean.md", "content": "__REPORT__"}}]},
        {"thought": "違反はなかった。報告して終わる。",
         "final": "基準額以上で未承認の申請はありませんでした。会議室の予約は不要です。"},
    ],
}

# 同じツールを呼び続けて前に進まない（停滞）。ループ上限で止まることを見る
STUCK = {
    "name": "state_stuck",
    "turns": [
        {"thought": "まず規程を読む。"},
        {"thought": "規程を読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "もう一度確認しておく。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "念のためもう一度。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
    ],
}

# 段階を飛ばして副作用のあるツールを呼びに行く（権限逸脱）。状態が止める
OUT_OF_ORDER = {
    "name": "state_out_of_order",
    "turns": [
        {"thought": "会議室から押さえてしまおう。"},
        {"thought": "先に報告会の部屋を取る。",
         "calls": [{"name": "book_room", "args": {"room": "みなと", "minutes": 60}}]},
        {"thought": "断られたので規程から読む。",
         "calls": [{"name": "get_policy", "args": {"topic": "経費精算"}}]},
        {"thought": "申請一覧を取る。",
         "calls": [{"name": "list_expenses", "args": {"status": "all"}}]},
    ],
}
