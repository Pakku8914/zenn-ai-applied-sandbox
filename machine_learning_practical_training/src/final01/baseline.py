"""課題2: ベースラインを先に置く。

モデルを学習する**前に**「何も学習していない予測」の点数を出しておきます。
先に置いておけば、あとで出た accuracy を見て一瞬でも喜ばずに済みます。

使い方:
    docker compose exec lab python src/final01/baseline.py
"""

from __future__ import annotations

from common import baseline, dataset


def main() -> None:
    data = dataset()
    base = baseline()

    print("■ 1. 何も学習しない予測を作る")
    print(f"訓練データの多数クラス: {base['major']}（{'再購入あり' if base['major'] == 1 else '再購入なし'}）")
    print(f"→ 評価データ {data['n_test']:,} 人全員に「再購入する」と答える予測にする")
    print()

    print("■ 2. ベースラインの点数")
    print(f"accuracy : {base['accuracy']:.4f}")
    print(f"ROC AUC  : {base['roc_auc']:.4f}（全員に同じ確率を返すので順位が付かない）")
    print(f"PR-AUC   : {base['pr_auc']:.4f}（評価データの正例率と一致する）")
    print()

    print("■ 3. この点数の意味")
    print(f"評価データの正例率: {base['positive_rate_test']:.4f}")
    print(f"accuracy {base['accuracy']:.4f} は、正例率をそのまま写した数です。")
    print("業務の言葉に直すと「全員にクーポンを送る」方針と同じで、")
    print("誰に送るかを何も選んでいません。")
    print()
    print("判断: これから作るモデルは、この 3 つの数を上回って初めて意味を持ちます。")
    print("      とくに ROC AUC 0.5000 は『順位が付いていない』状態の点数です。")


if __name__ == "__main__":
    main()
