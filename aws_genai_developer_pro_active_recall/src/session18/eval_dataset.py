#!/usr/bin/env python3
"""セッション18: ゴールデンデータセット（何を測るかを先に決める）。

    docker compose exec app python src/session18/eval_dataset.py

評価データは「質問の一覧」ではありません。1件につき**採点に使える正解**を持たせます。

    question   利用者が実際に打ちそうな文
    docId      その質問に答えられる正解文書（**検索**の採点に使う）
    category   その質問が属する分類（分類フィルタの検証に使う）
    goldValue  回答に必ず含まれていなければならない値（**生成**の採点に使う）

`docId` が `None` の質問を2件混ぜてあります。全件が答えられる評価データでは
**「断るべきときに断れるか」が測れません。** ハルシネーション率はここでだけ測れます。

**この教材のモック固有の注意:** 質問と資料が漢字語を共有していないと、モックの
生成器は「資料の範囲外」と応答します（`requirements.md`「モックの既知の癖」）。
q-09 / q-10 はその癖を踏むように**意図して**入れてあります。検索は当たっているのに
生成が答えられない件があることが、評価を検索と生成に分ける理由そのものです。
"""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_PATH = Path("/workspace/fixtures/kb_corpus.json")

CATEGORIES = ("IT", "経費", "人事", "セキュリティ")

# 分類フィルタを**わざと間違える**ときの対応表。正解文書の分類とは必ず別になる
WRONG_CATEGORY_OF = {"IT": "経費", "経費": "人事", "人事": "セキュリティ", "セキュリティ": "IT"}

# 12件。分類は4つとも3件ずつ（偏った評価データは偏った改善を導く）
GOLDEN: tuple[dict, ...] = (
    {
        "id": "q-01",
        "question": "有給休暇の繰越上限は何日ですか。",
        "docId": "hr-001",
        "category": "人事",
        "goldValue": "20日",
    },
    {
        "id": "q-02",
        "question": "在宅勤務は週に何日まで認められますか。",
        "docId": "hr-002",
        "category": "人事",
        "goldValue": "週3日",
    },
    {
        "id": "q-03",
        "question": "国内出張の宿泊費の上限はいくらですか。",
        "docId": "ex-001",
        "category": "経費",
        "goldValue": "15000円",
    },
    {
        "id": "q-04",
        "question": "備品の購入で購買部の見積取得が必要になる金額はいくらからですか。",
        "docId": "ex-003",
        "category": "経費",
        "goldValue": "3万円以上",
    },
    {
        "id": "q-05",
        "question": "認証の失敗が何回続くとアカウントがロックされますか。",
        "docId": "hd-002",
        "category": "IT",
        "goldValue": "5回連続",
    },
    {
        "id": "q-06",
        "question": "貸与PCの交換申請には何が必要ですか。",
        "docId": "hd-003",
        "category": "IT",
        "goldValue": "資産管理番号",
    },
    {
        "id": "q-07",
        "question": "社内情報の格付けは何段階ですか。",
        "docId": "sec-001",
        "category": "セキュリティ",
        "goldValue": "4段階",
    },
    {
        "id": "q-08",
        "question": "情報漏えいの一次報告はいつまでに行いますか。",
        "docId": "sec-002",
        "category": "セキュリティ",
        "goldValue": "30分以内",
    },
    # ここから2件は**カタカナ語だけで聞いている**。資料に答えはあるが、質問と資料が
    # 漢字語を共有しないためモックの生成器は答えられない（＝生成側の既知の不具合）
    {
        "id": "q-09",
        "question": "パスワードリセットの手順を教えてください。",
        "docId": "hd-002",
        "category": "IT",
        "goldValue": "社内ポータル",
    },
    {
        "id": "q-10",
        "question": "セキュリティインシデントの報告先はどこですか。",
        "docId": "sec-002",
        "category": "セキュリティ",
        "goldValue": "セキュリティ窓口",
    },
    # ここから2件は**資料に答えが無い**。断れれば正解（作り話をしたら不正解）
    {
        "id": "q-11",
        "question": "駐車場の月極料金はいくらですか。",
        "docId": None,
        "category": "経費",
        "goldValue": None,
    },
    {
        "id": "q-12",
        "question": "社員食堂の営業時間は何時までですか。",
        "docId": None,
        "category": "人事",
        "goldValue": None,
    },
)

# 読者が足す枠。`gate.py` は GOLDEN ＋ EXTRA を採点する（練習問題で使う）
EXTRA: list[dict] = []


def documents() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


DOC_ID_BY_URI: dict[str, str] = {doc["uri"]: doc["id"] for doc in documents()}
URI_OF: dict[str, str] = {doc["id"]: doc["uri"] for doc in documents()}


def rows() -> tuple[dict, ...]:
    """採点対象の全件（読者が足した分も含む）。"""
    return tuple(GOLDEN) + tuple(EXTRA)


def answerable(source: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
    """正解文書がある質問（検索の採点対象）。"""
    return tuple(row for row in (source or rows()) if row["docId"] is not None)


def unanswerable(source: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
    """資料に答えが無い質問（断れたかを測る対象）。"""
    return tuple(row for row in (source or rows()) if row["docId"] is None)


def coverage(source: tuple[dict, ...] | None = None) -> tuple[int, int]:
    """(正解文書として1度でも出てくる文書数, コーパスの文書数)。

    カバレッジが低い評価データは、触っていない文書の劣化に気づけません。
    """
    covered = {row["docId"] for row in answerable(source)}
    return len(covered), len(DOC_ID_BY_URI)


def category_counts(source: tuple[dict, ...] | None = None) -> dict[str, int]:
    counts = {category: 0 for category in CATEGORIES}
    for row in source or rows():
        counts[row["category"]] += 1
    return counts


def main() -> None:
    data = rows()
    covered, total = coverage(data)
    print("=== ゴールデンデータセット ===")
    print(
        f"  質問 {len(data)} 件"
        f"（資料から答えられる {len(answerable(data))} / 答えが無い {len(unanswerable(data))}）"
    )
    print(f"  正解文書のカバレッジ: {total} 文書のうち {covered} 件")
    counts = category_counts(data)
    print("  分類の内訳: " + " / ".join(f"{name} {counts[name]}" for name in CATEGORIES))
    print()
    print("=== 1件の中身 ===")
    print(json.dumps(GOLDEN[0], ensure_ascii=False))
    print(json.dumps(GOLDEN[10], ensure_ascii=False))


if __name__ == "__main__":
    main()
