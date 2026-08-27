"""あなたの答えを書くファイル（復習01の問題1・問題2・問題10）。

**練習問題を解く前に、この3つの辞書の中身を消してから始めてください。**
（`Q1 = {}` のように空にする。元に戻したいときは `git checkout src/review01/answers.py`）

答え合わせは機械が行う。

    docker compose exec app python src/review01/verify.py
"""

from __future__ import annotations

# --- 問題1：6本の軌跡のうち4本について（停止理由, 失敗モードの並び）------------
# 失敗モードは "暴走" / "停滞" / "誤選択" / "幻覚" / "権限逸脱" の順に並べる。
# 該当なしは空のリストにする。
Q1 = {
    "A_normal": ("done", []),
    "B_stuck_loop": ("max_steps", ["暴走", "停滞"]),
    "C_rephrase_loop": ("max_steps", ["暴走"]),
    "D_false_report": ("done", ["誤選択", "幻覚", "権限逸脱"]),
}

# --- 問題2：4つの業務要求の振り分けと上限設計 --------------------------------
# choice は "ワークフロー" / "ツール付き単発呼び出し" / "エージェント"。
# エージェントを選んだものだけ max_steps と on_limit も書く。
Q2 = {
    "請求書の区分付け": {"choice": "ツール付き単発呼び出し"},
    "月次の経費集計": {"choice": "ワークフロー"},
    "監査指摘の洗い出し": {"choice": "エージェント", "max_steps": 7, "on_limit": "partial"},
    "取引先への謝罪文送付": {"choice": "エージェント", "max_steps": 6, "on_limit": "handoff"},
}

# --- 問題10：4件の障害報告の切り分け ----------------------------------------
# causes は diagnose.CAUSES の並び順で書く。first は最初に手を入れるセッション。
Q10 = {
    "INC-01": {"causes": ["計画がない"], "first": "S05"},
    "INC-02": {"causes": ["道具のエラーが不親切", "道具の粒度が粗い"], "first": "S04"},
    "INC-03": {"causes": ["上限不足"], "first": "S03"},
    "INC-04": {"causes": ["報告が実態と違う"], "first": "S02"},
}
