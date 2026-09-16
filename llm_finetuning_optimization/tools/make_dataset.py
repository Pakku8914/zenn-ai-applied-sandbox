#!/usr/bin/env python3
"""みなと商事のヘルプデスク問い合わせデータセットを生成する（決定的）。

固定シード・固定基準日で動くため、何度実行しても同じ結果になる。

3つのタスクを1つのコーパスから作る:
  1. 分類（classify）  : 問い合わせを6区分のどれかに振る。**正解率で測れる**
  2. 整形（format）    : 定型フォーマットで回答する。**形式の遵守率で測れる**
  3. 選好（preference）: 良い回答と悪い回答のペア（DPO 用）

出力:
  data/train.jsonl / data/valid.jsonl / data/test.jsonl   分類＋整形
  data/preference.jsonl                                    DPO 用のペア
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260815
OUT = Path(__file__).resolve().parent.parent / "data"

CATEGORIES = ["経費", "勤怠", "PC", "アカウント", "オフィス", "セキュリティ"]

# 区分ごとの「担当」「期限」。整形タスクの正解の根拠になる
META = {
    "経費": ("経理部", "支出日から10日以内"),
    "勤怠": ("総務部", "取得予定日の3営業日前"),
    "PC": ("情報システム部", "申請から3営業日"),
    "アカウント": ("情報システム部", "アカウント発行から5営業日以内"),
    "オフィス": ("総務部", "利用日の前日まで"),
    "セキュリティ": ("情報セキュリティ室", "発見から1時間以内"),
}

# 問い合わせの言い回しの型（区分 → 表現のリスト）
PHRASES = {
    "経費": ["交通費の精算はどうすればいいですか", "領収書を紛失した場合の精算方法",
             "出張旅費の締切を教えてください", "接待交際費の事前承認が必要な金額",
             "立替金はいつ振り込まれますか", "備品購入の決裁区分を知りたい"],
    "勤怠": ["有給休暇の申請はいつまでですか", "遅刻したときの連絡先",
             "残業の事前申請の上限時間", "代休はいつまでに取ればよいですか",
             "打刻を忘れた場合の修正方法", "育児休業の申出期限"],
    "PC": ["貸与PCの初期設定にかかる時間", "PCが起動しなくなりました",
           "ソフトウェアのインストール申請の審査期間", "外付けモニタを借りたい",
           "退職時のPC返却期限", "貸与スマートフォンの通信費の上限"],
    "アカウント": ["入社時のアカウントはいつ発行されますか", "パスワードを忘れてロックされました",
                   "多要素認証の登録期限", "権限変更申請の承認者は誰ですか",
                   "退職者のアカウントはいつ停止されますか", "共有アカウントの棚卸頻度"],
    "オフィス": ["会議室の連続利用の上限", "入退館カードを紛失しました",
                 "座席に私物を置いたままでよいですか", "郵便物の集配時刻",
                 "駐車場の月額利用料", "共用備品の持ち出しの記録方法"],
    "セキュリティ": ["資料を社外に持ち出す場合の申請", "不審なメールが届きました",
                     "USBメモリは使ってよいですか", "外部サービスの利用申請の審査期間",
                     "情報漏洩を発見した場合の報告期限", "機密文書の保管期間"],
}

# 言い回しを増やすための接頭・接尾（データ量を確保しつつ多様性を持たせる）
PREFIX = ["", "お世話になります。", "恐れ入りますが、", "初めて手続きします。", "急ぎで確認したいのですが、"]
SUFFIX = ["", "教えてください。", "よろしくお願いします。", "ご確認をお願いします。", "至急お願いします。"]


def answer_text(category: str) -> str:
    """整形タスクの正解。この形式を厳密に守らせることが学習の目的。"""
    owner, deadline = META[category]
    return f"【区分】{category}\n【担当】{owner}\n【期限】{deadline}"


def bad_answer_text(category: str) -> str:
    """選好学習（DPO）で「選ばれない側」に使う回答。形式を守っていない。"""
    owner, deadline = META[category]
    return f"{category}のことですね。{owner}に聞いてください。期限は{deadline}くらいです。"


def build_examples(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    n = 0
    for category, phrases in PHRASES.items():
        for phrase in phrases:
            for prefix in PREFIX:
                for suffix in SUFFIX:
                    n += 1
                    question = f"{prefix}{phrase}{suffix}".strip()
                    rows.append({
                        "id": f"Q-{n:04d}",
                        "question": question,
                        "category": category,
                        "answer": answer_text(category),
                    })
    rng.shuffle(rows)
    return rows


def main() -> None:
    rng = random.Random(SEED)
    rows = build_examples(rng)

    # 8:1:1 で分割する。同じ言い回しが train と test にまたがらないよう
    # 「型（phrase）」単位で分けるのが本来望ましいが、その設計はセッション3の題材にする。
    # ここでは素朴なランダム分割にしておき、汚染（leakage）を読者に発見させる。
    n = len(rows)
    n_valid = n_test = n // 10
    valid = rows[:n_valid]
    test = rows[n_valid : n_valid + n_test]
    train = rows[n_valid + n_test :]

    OUT.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("valid", valid), ("test", test)):
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for row in part:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # DPO 用のペア（train の一部から作る）
    with (OUT / "preference.jsonl").open("w", encoding="utf-8") as f:
        for row in train[:200]:
            f.write(json.dumps({
                "id": row["id"], "prompt": row["question"],
                "chosen": row["answer"], "rejected": bad_answer_text(row["category"]),
            }, ensure_ascii=False) + "\n")

    from collections import Counter

    print(f"train={len(train)} valid={len(valid)} test={len(test)} preference=200")
    print(f"区分の分布（train）: {dict(sorted(Counter(r['category'] for r in train).items()))}")
    print(f"言い回しの型の数    : {sum(len(v) for v in PHRASES.values())}"
          f"（区分 {len(CATEGORIES)} × 各 {len(next(iter(PHRASES.values())))}）")
    print(f"1件あたりの平均文字数: 質問 "
          f"{sum(len(r['question']) for r in rows) / len(rows):.1f} / 回答 "
          f"{sum(len(r['answer']) for r in rows) / len(rows):.1f}")


if __name__ == "__main__":
    main()
